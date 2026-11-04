from __future__ import annotations

import logging
import hashlib
import random
import time
from collections import Counter
from uuid import uuid4

from .errors import ExpiredMedia, ProviderError, UnsafeMedia
from .media import download_image, permalink
from .services import classify, photo_allowed, telegram
from .cache import assessment

LOG = logging.getLogger("tigerwatch")


class Worker:
    def __init__(self, cfg, state, meta, http, *, clock=time.time, sleep=time.sleep, downloader=download_image):
        self.cfg, self.state, self.meta, self.http = cfg, state, meta, http
        self.clock, self.sleep, self.downloader = clock, sleep, downloader
        self.metrics = Counter()
        self.start = clock()
        self.refreshed = set()

    def remaining(self):
        return self.cfg.max_runtime - (self.clock() - self.start)

    def cooldown(self, provider):
        until = self.state.kv_get("cooldown/" + provider) or 0
        return max(0, until - self.clock()) if type(until) in (int, float) else 0

    def finish(self, item, status, reason="", *, keep=False):
        self.state.save(item, release=True, status=status, last_error=reason,
                        data=item["data"] if keep else {}, progress={})
        self.metrics[status] += 1

    def defer(self, item, delay, reason, *, failure=False):
        attempts = item["attempts"] + int(failure)
        if attempts >= self.cfg.max_attempts:
            self.finish(item, "dead", reason)
            return
        self.state.save(item, release=True, status="retry", attempts=attempts,
                        next_attempt=self.clock() + max(1, delay), last_error=reason)
        self.metrics["deferred"] += 1

    def error(self, item, exc):
        self.metrics["provider_errors"] += 1
        if exc.unknown:
            # No Telegram idempotency key: do not blindly send twice after a timeout.
            self.finish(item, "review", "telegram:delivery_unknown", keep=True)
        elif not exc.retry and not exc.stop:
            self.finish(item, "dead", str(exc))
        else:
            delay = max(exc.wait, min(21600, self.cfg.retry_seconds * 2 ** item["attempts"]) * random.uniform(1, 1.2))
            self.defer(item, delay, str(exc), failure=not exc.stop)
        if exc.stop:
            self.state.kv_set("cooldown/" + exc.provider, self.clock() + max(exc.wait, self.cfg.retry_seconds))
            raise exc

    def reserve(self, item, resource, daily, interval):
        for _ in range(2):
            if self.remaining() < 80:
                self.defer(item, 60, "run_time_cap")
                return False
            self.state.save(item, progress=item["progress"])
            value = self.state.reserve(resource, daily, interval)
            if value["ok"]:
                return True
            if value["reason"] == "pace" and value["wait"] <= 60:
                self.sleep(value["wait"] + 0.05)
                continue
            self.defer(item, value["wait"], resource + "_daily_budget")
            self.metrics[resource + "_budget_exhausted"] += 1
            return False
        self.defer(item, interval, resource + "_pacing")
        return False

    def refresh(self, item):
        if item["id"] in self.refreshed:
            return False
        self.refreshed.add(item["id"])
        data = self.meta.refresh(item["source"], item["id"])
        if data:
            self.state.save(item, data=data)
            self.metrics["url_refreshes"] += 1
            return True
        return False

    @staticmethod
    def images(item):
        data = item["data"]
        if data.get("media_type") == "IMAGE":
            return [{"id": item["id"], "media_url": data.get("media_url")}]
        return [x for x in data.get("children", []) if x.get("media_type") == "IMAGE"]

    def image(self, item, child_id):
        def current_url():
            return next((x.get("media_url") for x in self.images(item) if x["id"] == child_id), None)
        url = current_url()
        if not url and self.refresh(item):
            url = current_url()
        if not url:
            raise ExpiredMedia()
        try:
            return self.downloader(self.http, url)
        except ExpiredMedia:
            if not self.refresh(item):
                raise
            new_url = current_url()
            if not new_url:
                raise ExpiredMedia() from None
            return self.downloader(self.http, new_url)

    def block_unsafe_media(self, item):
        """New safety metadata supersedes any older positive/delivery intent."""
        if not item["data"].get("media_blocked"):
            return False
        result = {"source_link": permalink(item["data"].get("permalink")), "media_not_processed": True}
        if item.get("result", {}).get("sending"):
            result["delivery_unknown"] = True
        self.state.save(item, result=result)
        self.finish(item, "review", "media_safety_block")
        return True

    def notify(self, item, jpg=None):
        if self.block_unsafe_media(item):
            return
        if self.cfg.alerts_enabled and self.metrics["alerts"] >= self.cfg.alerts_run:
            self.defer(item, 3600, "alerts_run_budget")
            return
        wait = self.cooldown("telegram") if self.cfg.alerts_enabled else 0
        if wait:
            self.defer(item, wait, "telegram_cooldown")
            return
        data, result = item["data"], item["result"]
        link = permalink(data.get("permalink"))
        if not link:
            if not self.refresh(item):
                self.finish(item, "review", "permalink_unavailable")
                return
            if self.block_unsafe_media(item):
                return
            link = permalink(item["data"].get("permalink"))
            if not link:
                self.finish(item, "review", "permalink_unavailable")
                return
        if not result.get("review_only") and photo_allowed(self.cfg, item["source"], item["id"]):
            if jpg is None:
                try:
                    jpg = self.image(item, result["child_id"])
                except (ProviderError, UnsafeMedia):
                    # Safe link fallback before any Telegram attempt has been made.
                    jpg = None
        else:
            jpg = None
        if self.block_unsafe_media(item):
            return
        ids = {x.get("id") for x in result.get("detections", [])}
        subjects = [q.description for i, q in enumerate(self.cfg.target.all_queries, 1) if "q" + str(i) in ids]
        summary = "; ".join(subjects or [self.cfg.target.description])[:300]
        sale_kind = "wildlife sale" if self.cfg.monitor_mode == "wildlife_sales" else "sale"
        heading = f"Possible {sale_kind} — human review required" if result.get("review_only") else "Possible match"
        message = (f"🔎 {heading}: {summary}\n"
                   f"Source: {item['source']}\nAI score (uncalibrated): {result['confidence']:.2f}\n"
                   f"Instagram: {link}\nAuthenticity and legality are unverified; do not treat this as an accusation.")
        if not self.cfg.alerts_enabled:
            self.state.save(item, result={**result, "source_link": link})
            self.finish(item, "review", "possible_sale" if result.get("review_only") else "local_match")
            return
        if not self.reserve(item, "alerts", self.cfg.alerts_day, self.cfg.alert_interval):
            return
        # A durable send marker prevents a crashed process from silently resending.
        result = {**result, "sending": True}
        self.state.save(item, result=result)
        try:
            message_id = telegram(self.http, message, jpg)
        except ProviderError as exc:
            if not exc.unknown:
                self.state.save(item, result={**result, "sending": False})
            self.error(item, exc)
            return
        self.state.save(item, result={**result, "sending": False, "message_id": message_id})
        self.finish(item, "review" if result.get("review_only") else "alerted",
                    "possible_sale" if result.get("review_only") else "")
        self.metrics["alerts"] += 1

    def assess_image(self, item, child_id):
        """Reuse exact pixels before checking AI quotas; fence cache misses."""
        jpg = self.image(item, child_id)
        key, token, claimed = hashlib.sha256(jpg).hexdigest(), uuid4().hex, False
        use_cache = not self.cfg.needs_sale_context
        try:
            if use_cache:
                for _ in range(2):
                    entry = self.state.cache_claim(key, token, lease=300)
                    if entry.get("status") != "hit":
                        break
                    try:
                        value = assessment(self.cfg, entry.get("value"))
                    except (ValueError, TypeError, KeyError, RecursionError):
                        self.metrics["invalid_cache_entries"] += 1
                        self.state.cache_invalidate(key)
                        continue
                    self.metrics["cache_hits"] += 1
                    return value, jpg
                if entry.get("status") == "busy":
                    self.metrics["cache_busy"] += 1
                    self.defer(item, entry.get("wait", 60), "cache_assessment_in_progress")
                    return None
                if entry.get("status") != "claimed":
                    raise ProviderError("cache", "invalid_assessment", retry=False)
                claimed = True
            if self.metrics["ai_budget_exhausted"]:
                self.defer(item, 86400 - self.clock() % 86400 + 1, "ai_daily_budget")
                return None
            if self.metrics["ai_attempts"] >= self.cfg.ai_run:
                self.defer(item, 3600, "ai_run_budget")
                return None
            wait = self.cooldown("gemini")
            if wait:
                self.defer(item, wait, "gemini_cooldown")
                return None
            if not self.reserve(item, "ai", self.cfg.ai_day, self.cfg.ai_interval):
                return None
            self.metrics["ai_attempts"] += 1
            decision = classify(self.http, self.cfg, jpg, sale_context=item["data"].get("sale_signals"))
            if claimed:
                canonical = assessment(self.cfg, decision)
                if self.state.cache_commit(key, token, canonical):
                    claimed = False
                else:
                    self.metrics["cache_store_skipped"] += 1
            return decision, jpg
        finally:
            if claimed:
                self.state.cache_release(key, token)

    def process_item(self, item):
        approved = tuple("#" + x for x in self.cfg.tags) + tuple("@" + x for x in self.cfg.accounts)
        if item["source"] not in approved:
            self.finish(item, "dead", "source_removed_from_configuration")
            return
        if self.block_unsafe_media(item):
            return
        result = item["result"]
        if result.get("sending"):
            self.finish(item, "review", "telegram:delivery_unknown", keep=True)
            return
        if result.get("message_id"):
            self.finish(item, "review" if result.get("review_only") else "alerted",
                        "possible_sale" if result.get("review_only") else "")
            return
        if result.get("match"):
            self.notify(item)
            return
        if item["data"].get("media_type") == "VIDEO":
            self.finish(item, "unsupported", "video_not_processed")
            return
        if item["data"].get("needs_hydration"):
            if not self.refresh(item):
                raise ExpiredMedia()
        if self.block_unsafe_media(item):
            return
        if item["data"].get("media_type") == "VIDEO":
            self.finish(item, "unsupported", "video_not_processed")
            return
        if item["data"].get("media_type") not in ("IMAGE", "CAROUSEL_ALBUM"):
            if not self.refresh(item):
                raise ExpiredMedia()
        if not self.images(item):
            self.refresh(item)
        images = self.images(item)
        if not images:
            if item["data"].get("children_complete"):
                self.finish(item, "unsupported", "carousel_has_no_photos")
                return
            raise ExpiredMedia()
        failures, borderline = [], False
        for image in images[:self.cfg.max_children]:
            child_id = image["id"]
            if child_id in item["progress"]:
                borderline |= item["progress"][child_id].get("review", False)
                continue
            try:
                cache_hits = self.metrics["cache_hits"]
                assessed = self.assess_image(item, child_id)
                if assessed is None:
                    return
                decision, jpg = assessed
                reused = self.metrics["cache_hits"] > cache_hits
            except UnsafeMedia:
                self.finish(item, "dead", "unsafe_media")
                return
            except ProviderError as exc:
                if exc.stop:
                    self.error(item, exc)
                failures.append(exc)
                continue
            if not decision["allowed_target"]:
                self.finish(item, "unsupported", "target_not_supported")
                return
            is_match = decision["match"]
            if is_match:
                result = {"match": True, "confidence": decision["confidence"], "child_id": child_id,
                          "model": decision["model"], "target_scope": self.cfg.scope,
                          "detections": decision["accepted"], "classified_at": self.clock(),
                          "review_only": decision.get("review_only", False),
                          "assessment_reused": reused,
                          "source_link": permalink(item["data"].get("permalink"))}
                # Persist the positive before attempting delivery; retries skip Gemini.
                self.state.save(item, result=result, attempts=0)
                self.notify(item, jpg)
                return
            review = decision["review"] or decision["needs_video"]
            borderline |= review
            progress = {**item["progress"], child_id: {**decision, "review": review}}
            self.state.save(item, progress=progress)
        if failures:
            self.error(item, failures[0])
        elif borderline or (item["data"].get("media_type") == "CAROUSEL_ALBUM" and not item["data"].get("children_complete")):
            self.finish(item, "review", "borderline_or_incomplete_carousel", keep=True)
        else:
            self.finish(item, "rejected")

    def run(self, *, discover=True):
        self.cfg.target.validate()
        self.state.maintain()
        if self.state.stats().get("today", {}).get("ai", 0) >= self.cfg.ai_day:
            self.metrics["ai_budget_exhausted"] = 1
        if discover:
            for source_number, label in enumerate(tuple("#" + x for x in self.cfg.tags) + tuple("@" + x for x in self.cfg.accounts), 1):
                if self.remaining() < 150:
                    break
                try:
                    rows = self.meta.source(label)
                    self.metrics["fetched"] += len(rows)
                except ProviderError as exc:
                    self.metrics["source_errors"] += 1
                    LOG.error("Configured source %s failed: %s (see troubleshooting)", source_number, exc)
                    if exc.stop:
                        self.state.kv_set("cooldown/" + exc.provider, self.clock() + max(exc.wait, self.cfg.retry_seconds))
                        if not exc.retry:
                            raise
                        break
        for _ in range(self.cfg.max_items):
            if self.remaining() < 80:
                break
            item = self.state.claim()
            if item is None:
                break
            self.metrics["claimed"] += 1
            try:
                self.process_item(item)
            except ProviderError as exc:
                if item.get("status") == "processing":
                    try:
                        self.error(item, exc)
                    except ProviderError:
                        pass
                if exc.stop:
                    LOG.error("Worker paused: %s", exc)
                    self.metrics["stopped"] += 1
                    break
        LOG.info("Run metrics: %s; state: %s", dict(self.metrics), self.state.stats())
        return dict(self.metrics)
