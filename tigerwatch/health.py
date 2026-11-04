"""Private operational summaries; no post URLs, captions or credential values."""
from __future__ import annotations

import logging
import math
import os
import re
import time
from uuid import uuid4

from .errors import ProviderError, SetupError
from .services import telegram
from .worker import Worker

LOG = logging.getLogger("tigerwatch")


def build_summary(cfg, state, *, clock=time.time, expected_interval=3600):
    now = clock()
    result = state.dashboard_snapshot()
    last = state.kv_get("health/" + cfg.scope + "/last")
    last = last if isinstance(last, dict) else None
    cooldowns = {}
    for provider in ("meta", "browser", "gemini", "telegram"):
        until = state.kv_get("cooldown/" + provider)
        if type(until) in (int, float) and math.isfinite(until) and until > now:
            cooldowns[provider] = round(until - now)
    used_ai = result["today"].get("ai", 0)
    used_alerts = result["today"].get("alerts", 0)
    pending = result["backlog"].get("pending", 0)
    warnings = []
    if used_ai >= cfg.ai_day:
        warnings.append("ai_budget_exhausted")
    if pending and (not cfg.ai_day or pending > cfg.ai_day * cfg.queue_hours / 24):
        warnings.append("backlog_may_expire_before_analysis")
    if result["backlog"].get("oldest_age_seconds", 0) >= cfg.queue_hours * 3600 * .8:
        warnings.append("oldest_items_near_expiry")
    if cooldowns:
        warnings.append("provider_cooldown")
    stale_after = max(10800, expected_interval * 1.5 + cfg.max_runtime)
    if not last:
        status = "not_run"
    elif last.get("status") == "running":
        status = "running" if now - last.get("started_at", 0) <= cfg.max_runtime + 120 else "interrupted_or_stale"
    elif now - last.get("finished_at", 0) > stale_after:
        status = "stale"
    else:
        status = last.get("status", "unknown")
    required = ["GEMINI_API_KEY"]
    if cfg.source_kind == "meta":
        required += ["META_ACCESS_TOKEN", "IG_USER_ID"]
    if cfg.alerts_enabled:
        required += ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    missing = [k for k in required if not os.getenv(k) or os.getenv(k) == "REPLACE_ME"]
    return {**result, "status": status, "last_run": last, "stale_after_seconds": stale_after, "cooldowns_seconds": cooldowns,
            "warnings": warnings, "budgets": {"ai_limit": cfg.ai_day, "ai_remaining": max(0, cfg.ai_day - used_ai),
            "alert_limit": cfg.alerts_day, "alerts_remaining": max(0, cfg.alerts_day - used_alerts),
            "reset": "UTC midnight; provider reset may differ"},
            "configuration": {"missing_credentials": missing, "free_plan_attested": cfg.free_plans_confirmed,
                              "analysis_rights_attested": cfg.analysis_rights_confirmed, "alerts_enabled": cfg.alerts_enabled},
            "score_is_uncalibrated": True, "automatic_submission": False}


def send_digest(cfg, state, http, *, clock=time.time, sleep=time.sleep):
    """One reserved attempt per UTC day/store, shared alert cap, no blind retry."""
    cfg.require_free()
    if not cfg.alerts_enabled:
        raise SetupError("Daily digest requires ALERTS_ENABLED=true and an explicitly configured bot")
    cfg.require("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    until = state.kv_get("cooldown/telegram")
    if type(until) in (int, float) and math.isfinite(until) and until > clock():
        return {"status": "telegram_cooldown", "wait": round(until - clock())}
    reservation = state.reserve_digest(cfg.alerts_day, cfg.alert_interval)
    if not reservation["ok"] and reservation["reason"] == "pace" and reservation["wait"] <= 60:
        sleep(reservation["wait"] + .05)
        reservation = state.reserve_digest(cfg.alerts_day, cfg.alert_interval)
    if not reservation["ok"]:
        return {"status": "already_attempted_today" if reservation.get("resource") == "digests" else "alert_budget_or_pacing"}
    summary = build_summary(cfg, state, clock=clock)
    message = ("VisualWatch private health summary\n"
               f"Last run: {summary['status']}\n"
               f"Queue: {summary['queue']}\n"
               f"Pending: {summary['backlog'].get('pending', 0)}; "
               f"oldest age: {round(summary['backlog'].get('oldest_age_seconds', 0) / 3600, 1)} hours\n"
               f"AI reservations today: {summary['today'].get('ai', 0)}/{cfg.ai_day}\n"
               f"Alert reservations today: {summary['today'].get('alerts', 0)}/{cfg.alerts_day}\n"
               f"Warnings: {', '.join(summary['warnings']) or 'none'}\n"
               "Counts describe this watch's current queue; daily reservations cover the whole store. "
               "No matches does not prove nothing was missed. Legality/authenticity unverified.")
    # A timed-out send consumes today's attempt to avoid uncertain duplicate delivery.
    return {"status": "sent", "message_id": telegram(http, message)}


def run_monitor(cfg, state, source, http, *, discover=True, worker_factory=Worker, clock=time.time):
    token = uuid4().hex
    if not state.run_begin(token, lease=min(1800, cfg.max_runtime + 300)):
        LOG.info("A monitor is already active for this watch; no second cycle started")
        return {"monitor_busy": 1}
    try:
        cfg.require_monitor()
        metrics = worker_factory(cfg, state, source, http).run(discover=discover)
    except BaseException as exc:
        code = str(exc) if isinstance(exc, ProviderError) and re.fullmatch(r"[a-zA-Z0-9_:.-]{1,96}", str(exc)) else type(exc).__name__
        state.run_finish(token, "failed", error=code)
        raise
    else:
        status = "partial" if any(metrics.get(x, 0) for x in ("source_errors", "stopped", "provider_errors")) else "completed"
        state.run_finish(token, status, metrics=metrics)
        return metrics
    finally:
        if cfg.daily_digest:
            try:
                send_digest(cfg, state, http, clock=clock)
            except Exception as exc:
                LOG.warning("Daily health digest unavailable: %s", type(exc).__name__)
