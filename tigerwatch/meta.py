"""Facebook Login endpoints only. See docs/API_VERIFICATION.md for references."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone

from .errors import ProviderError, SetupError
from .media import approved_cdn, permalink
from .net import json_request, retry_after
from .safety import child_safety_request, sale_signals

LOG = logging.getLogger("tigerwatch")
# Fetch children in the permitted discovery context, never GET third-party IDs.
FIELDS = "id,media_type,media_url,permalink,timestamp,children.limit(50){id,media_type,media_url}"


def numeric_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9]{1,50}", value))


def page_rows(value):
    if not isinstance(value, dict) or not isinstance(value.get("data"), list) or len(value["data"]) > 200:
        raise ProviderError("meta", "invalid_page")
    if any(not isinstance(x, dict) for x in value["data"]):
        raise ProviderError("meta", "invalid_media_row")
    return value["data"]


def cursor(page):
    paging = page.get("paging") or {}
    if not isinstance(paging, dict) or not isinstance(paging.get("cursors", {}), dict):
        raise ProviderError("meta", "invalid_paging")
    value = paging.get("cursors", {}).get("after")
    if value is None:
        return None
    # Prevent injection into Business Discovery's field expansion grammar.
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_+=/\-]{1,2048}", value):
        raise ProviderError("meta", "invalid_cursor")
    return value


def timestamp(value):
    try:
        if type(value) in (int, float) or (isinstance(value, str) and value.isdigit()):
            return datetime.fromtimestamp(float(value), timezone.utc).timestamp()
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp() if dt.tzinfo else None
    except (ValueError, AttributeError, TypeError, OverflowError, OSError):
        return None


def clean_post(post, cfg, now, *, recovering=False):
    """Minimize retained data and reject malformed API values at the boundary."""
    ident = post.get("id")
    link = permalink(post.get("permalink"))
    kind = post.get("media_type")
    if not numeric_id(ident) or not link or kind not in ("IMAGE", "VIDEO", "CAROUSEL_ALBUM"):
        return None
    published = timestamp(post.get("timestamp"))
    if published is not None and ((not recovering and published < now - cfg.post_hours * 3600) or published > now + 300):
        return None
    data = {"id": ident, "media_type": kind, "permalink": link}
    if child_safety_request(post.get("caption")):
        return {**data, "media_blocked": True}
    if cfg.needs_sale_context:
        data["sale_signals"] = sale_signals(post.get("caption"))
    if published is not None:
        data["timestamp"] = published
    if kind == "IMAGE" and approved_cdn(post.get("media_url")):
        data["media_url"] = post["media_url"]
    if kind == "CAROUSEL_ALBUM":
        children = post.get("children")
        if isinstance(children, dict):
            rows = page_rows(children)
            safe = []
            for child in rows[:50]:
                if not numeric_id(child.get("id")) or child.get("media_type") not in ("IMAGE", "VIDEO"):
                    continue
                entry = {"id": child["id"], "media_type": child["media_type"]}
                if child.get("media_type") == "IMAGE" and approved_cdn(child.get("media_url")):
                    entry["media_url"] = child["media_url"]
                safe.append(entry)
            data["children"] = safe
            # A truncated carousel can be positively matched, never fully rejected.
            paging = children.get("paging") or {}
            if not isinstance(paging, dict):
                raise ProviderError("meta", "invalid_children_paging")
            data["children_complete"] = not bool(paging.get("next")) and len(rows) <= cfg.max_children and len(safe) == len(rows)
        else:
            data["children"] = []
            data["children_complete"] = False
    return data


class Meta:
    def __init__(self, cfg, http, state, *, sleep=time.sleep, clock=time.time):
        self.cfg, self.http, self.state = cfg, http, state
        self.sleep, self.clock = sleep, clock
        self.user_id = os.getenv("IG_USER_ID", "")
        if not numeric_id(self.user_id):
            raise SetupError("IG_USER_ID must be the numeric professional account ID")
        self.base = f"https://graph.facebook.com/{cfg.version}/"
        self.token = os.getenv("META_ACCESS_TOKEN", "")
        self.calls = 0
        self.cache = {}

    @property
    def fields(self):
        return FIELDS + (",caption" if self.cfg.needs_sale_context else "")

    def get(self, path, **params):
        if not re.fullmatch(r"(?:[0-9]{1,50}(?:/recent_media|/recently_searched_hashtags)?|ig_hashtag_search|me/permissions)", path):
            raise SetupError("Unsupported Meta endpoint in this worker")
        app_secret = os.getenv("META_APP_SECRET", "")
        if app_secret:
            params["appsecret_proof"] = hmac.new(app_secret.encode(), self.token.encode(), hashlib.sha256).hexdigest()
        for attempt in range(3):
            until = self.state.kv_get("cooldown/meta") or 0
            if type(until) in (int, float) and until > self.clock():
                raise ProviderError("meta", "cooldown", stop=True, wait=until - self.clock())
            if self.calls >= self.cfg.max_meta_calls:
                raise ProviderError("meta", "run_request_cap", stop=True, wait=3600)
            self.calls += 1
            try:
                status, headers, body = json_request(self.http, "GET", self.base + path, "meta", raw_status=True,
                                                     params=params, headers={"Authorization": "Bearer " + self.token}, timeout=(8, 25))
            except ProviderError as exc:
                if exc.code != "transport" or attempt == 2:
                    raise
                self.sleep(2 ** attempt + random.random())
                continue
            err = body.get("error") if isinstance(body, dict) else None
            code = err.get("code") if isinstance(err, dict) else None
            if status in (401, 403) or code in (102, 190):
                raise ProviderError("meta", "authentication_or_permission", retry=False, stop=True)
            if status == 429 or code in (4, 17, 32, 613, 80004):
                raise ProviderError("meta", "rate_limit", stop=True, wait=retry_after(headers))
            if status >= 500 or (isinstance(err, dict) and err.get("is_transient") is True):
                wait = retry_after(headers, 2 ** attempt)
                if attempt < 2 and wait <= 8:
                    self.sleep(wait + random.random())
                    continue
                raise ProviderError("meta", "temporary_failure", stop=True, wait=max(60, wait))
            if not 200 <= status < 300 or err:
                # Never echo upstream message, request URL, or raw response body.
                safe_code = str(code) if type(code) is int else "unknown"
                raise ProviderError("meta", "request_denied_" + safe_code, retry=False)
            if not isinstance(body, dict):
                raise ProviderError("meta", "invalid_json")
            # Respect observed usage, without inventing a universal requests/hour quota.
            for name in ("x-app-usage", "x-page-usage", "x-business-use-case-usage"):
                raw = headers.get(name, headers.get(name.title(), "{}"))
                try:
                    usage = json.loads(raw)
                    if self._usage_high(usage):
                        self.state.kv_set("cooldown/meta", self.clock() + 3600)
                        LOG.warning("Meta usage header reached local 90%% safety threshold")
                except (ValueError, TypeError):
                    pass
            return body
        raise ProviderError("meta", "temporary_failure", stop=True)

    @classmethod
    def _usage_high(cls, obj):
        if isinstance(obj, dict):
            return any((k in ("call_count", "total_cputime", "total_time") and type(v) in (int, float) and v >= 90)
                       or cls._usage_high(v) for k, v in obj.items())
        return isinstance(obj, list) and any(cls._usage_high(x) for x in obj)

    def hashtag_media(self, tag):
        if tag not in self.cfg.tags:
            raise SetupError("Hashtag is not in the approved HASHTAGS configuration")
        if not self.state.admit_tag(self.user_id, tag):
            raise ProviderError("meta", "local_30_hashtag_window", retry=False)
        key = "tag/" + self.user_id + "/" + tag
        hid = self.state.kv_get(key)
        if not numeric_id(hid):
            rows = page_rows(self.get("ig_hashtag_search", user_id=self.user_id, q=tag))
            if not rows:
                return []
            hid = rows[0].get("id")
            if not numeric_id(hid):
                raise ProviderError("meta", "invalid_hashtag_id")
            self.state.kv_set(key, hid)
        results, seen, after = [], set(), None
        for _ in range(self.cfg.pages):
            params = {"user_id": self.user_id, "fields": self.fields, "limit": min(50, self.cfg.per_source - len(results))}
            if after:
                params["after"] = after
            page = self.get(hid + "/recent_media", **params)
            rows = [x for x in page_rows(page) if numeric_id(x.get("id"))]
            self.checkpoint("#" + tag, rows)
            fresh = [x for x in rows if x.get("id") not in seen]
            results.extend(fresh)
            seen.update(x.get("id") for x in fresh)
            after = cursor(page)
            # This endpoint can return the same after value on successive pages.
            # Bound requests and stop on repeated content, not repeated cursors.
            if not rows or not fresh or len(results) >= self.cfg.per_source or not after:
                break
        if after and len(results) >= self.cfg.per_source:
            LOG.info("Hashtag fetch capped; API coverage is bounded")
        return results[:self.cfg.per_source]

    def business_media(self, handle):
        if handle not in self.cfg.accounts:
            raise SetupError("Account is not in the approved ACCOUNTS configuration")
        results, seen, after = [], set(), None
        for _ in range(self.cfg.pages):
            edge = f"media.limit({min(50, self.cfg.per_source - len(results))})"
            if after:
                edge += ".after(" + after + ")"
            fields = f"business_discovery.username({handle}){{{edge}{{{self.fields}}}}}"
            data = self.get(self.user_id, fields=fields)
            discovery = data.get("business_discovery")
            if not isinstance(discovery, dict) or not isinstance(discovery.get("media"), dict):
                raise ProviderError("meta", "business_unavailable", retry=False)
            page = discovery["media"]
            rows = [x for x in page_rows(page) if numeric_id(x.get("id"))]
            self.checkpoint("@" + handle, rows)
            fresh = [x for x in rows if x.get("id") not in seen]
            results.extend(fresh)
            seen.update(x.get("id") for x in fresh)
            after = cursor(page)
            # Business Discovery provides cursors without next/previous URLs.
            if not rows or not fresh or len(results) >= self.cfg.per_source or not after:
                break
        return results[:self.cfg.per_source]

    def checkpoint(self, source, rows):
        # Commit each fetched page before asking Meta for another one.
        items = []
        for row in rows:
            data = clean_post(row, self.cfg, self.clock())
            if data:
                items.append({"id": data["id"], "source": source, "data": data})
        self.state.enqueue(items)

    def source(self, label, *, refresh=False):
        if not refresh and label in self.cache:
            return self.cache[label]
        until = self.state.kv_get("cooldown/meta") or 0
        if type(until) in (int, float) and until > self.clock():
            raise ProviderError("meta", "cooldown", stop=True, wait=until - self.clock())
        rows = self.hashtag_media(label[1:]) if label.startswith("#") else self.business_media(label[1:])
        self.cache[label] = rows
        return rows

    def refresh(self, source, media_id):
        # One additional source scan per source/run, never direct third-party ID reads.
        key = "refreshed:" + source
        if key not in self.cache:
            self.cache[key] = self.source(source, refresh=True)
        for row in self.cache[key]:
            if row.get("id") == media_id:
                return clean_post(row, self.cfg, self.clock(), recovering=True)
        return None

    def check_access(self):
        identity = self.get(self.user_id, fields="id,username")
        if identity.get("id") != self.user_id:
            raise ProviderError("meta", "identity_mismatch", retry=False)
        grants = self.get("me/permissions").get("data", [])
        if not isinstance(grants, list):
            raise ProviderError("meta", "invalid_permissions")
        granted = {r.get("permission") for r in grants if isinstance(r, dict) and r.get("status") == "granted"}
        needed = {"instagram_basic"}
        if self.cfg.accounts:
            needed |= {"instagram_manage_insights", "pages_read_engagement"}
        missing = sorted(needed - granted)
        if missing:
            raise SetupError("Meta token missing permissions: " + ", ".join(missing))
        if self.cfg.tags:
            self.source("#" + self.cfg.tags[0])
        if self.cfg.accounts:
            self.source("@" + self.cfg.accounts[0])
        LOG.info("Live metadata probes accepted; public-content App Review and image access still need verification")
