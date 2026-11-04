from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, replace

from .errors import SetupError
from .targets import Target, target_from_env

# Verified against official pricing; deliberately no paid model/fallback setting.
FREE_MODELS = frozenset({"gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"})


def csv(value):
    return tuple(dict.fromkeys(x.strip().lstrip("#@").casefold() for x in value.split(",") if x.strip()))


def integer(env, name, default, low, high):
    try:
        n = int(env.get(name) or default)
    except (ValueError, TypeError):
        raise SetupError(f"{name} must be an integer") from None
    if not low <= n <= high:
        raise SetupError(f"{name} must be between {low} and {high}")
    return n


def boolean(env, name, default=False):
    value = str(env.get(name) or str(default)).lower()
    if value not in ("true", "false", "1", "0", "yes", "no"):
        raise SetupError(f"{name} must be true or false")
    return value in ("true", "1", "yes")


def score(env, name, default):
    try:
        n = float(env.get(name) or default)
    except ValueError:
        raise SetupError(f"{name} must be numeric") from None
    if not math.isfinite(n) or not 0 <= n <= 1:
        raise SetupError(f"{name} must be between 0 and 1")
    return n


@dataclass(frozen=True)
class Config:
    target: Target = Target()
    free_plans_confirmed: bool = False
    tags: tuple = ()
    accounts: tuple = ()
    version: str = "v26.0"
    model: str = "gemini-3.1-flash-lite"
    per_source: int = 30
    pages: int = 3
    max_meta_calls: int = 80
    max_children: int = 20
    ai_run: int = 4
    ai_day: int = 20
    ai_interval: int = 6
    alerts_run: int = 3
    alerts_day: int = 10
    alert_interval: int = 4
    score: float = 0.85
    review_score: float = 0.65
    max_items: int = 60
    queue_hours: int = 72
    dedup_days: int = 90
    post_hours: int = 24
    max_attempts: int = 6
    retry_seconds: int = 300
    lease_seconds: int = 600
    max_runtime: int = 480
    send_photo: bool = False
    photo_sources: tuple = ()
    photo_media_ids: tuple = ()
    photo_rights_confirmed: bool = False
    analysis_rights_confirmed: bool = False
    sqlite_path: str = "tigerwatch.sqlite3"
    supabase_url: str = ""
    source_kind: str = "meta"
    monitor_mode: str = "general"
    alerts_enabled: bool = True
    browser_posts: int = 200
    browser_scrolls: int = 60
    browser_delay: int = 3
    browser_headless: bool = True
    daily_digest: bool = False

    @classmethod
    def from_env(cls, env=None):
        e = os.environ if env is None else env
        tags, accounts = csv(e.get("HASHTAGS", "")), csv(e.get("ACCOUNTS", ""))
        if len(tags) > 30 or any(not re.fullmatch(r"\w{1,100}", x) for x in tags):
            raise SetupError("HASHTAGS requires at most 30 names without spaces or emojis")
        if len(accounts) > 20 or any(not re.fullmatch(r"[a-z0-9._]{1,30}", x) for x in accounts):
            raise SetupError("ACCOUNTS requires at most 20 valid professional usernames")
        version = e.get("GRAPH_API_VERSION") or cls.version
        target = target_from_env(e, boolean)
        model = e.get("GEMINI_MODEL") or ("auto" if target != Target() else cls.model)
        if not re.fullmatch(r"v\d{2}\.0", version):
            raise SetupError("GRAPH_API_VERSION must have the form v26.0")
        if not re.fullmatch(r"[a-zA-Z0-9.-]{1,100}", model):
            raise SetupError("Invalid GEMINI_MODEL")
        photo_sources = tuple(dict.fromkeys(x.strip().casefold() for x in e.get("PHOTO_RESHARE_SOURCES", "").split(",") if x.strip()))
        if any(x not in tuple("@" + a for a in accounts) for x in photo_sources):
            raise SetupError("PHOTO_RESHARE_SOURCES must be exact configured @accounts with account-wide permission")
        photo_ids = csv(e.get("PHOTO_RESHARE_MEDIA_IDS", ""))
        if any(not re.fullmatch(r"[0-9]{1,50}", x) for x in photo_ids):
            raise SetupError("PHOTO_RESHARE_MEDIA_IDS must contain numeric post IDs")
        cfg = cls(
            target=target,
            free_plans_confirmed=boolean(e, "FREE_PLANS_CONFIRMED"),
            tags=tags, accounts=accounts, version=version, model=model,
            per_source=integer(e, "MAX_POSTS_PER_SOURCE", 30, 1, 150),
            pages=integer(e, "MAX_PAGES_PER_SOURCE", 3, 1, 6),
            max_meta_calls=integer(e, "MAX_META_CALLS_PER_RUN", 80, 1, 300),
            max_children=integer(e, "MAX_CAROUSEL_IMAGES", 20, 1, 50),
            ai_run=integer(e, "MAX_AI_CALLS_PER_RUN", 4, 0, 100),
            ai_day=integer(e, "MAX_AI_CALLS_PER_DAY", 20, 0, 1000),
            ai_interval=integer(e, "AI_MIN_INTERVAL_SECONDS", 6, 1, 60),
            alerts_run=integer(e, "MAX_ALERTS_PER_RUN", 3, 0, 50),
            alerts_day=integer(e, "MAX_ALERTS_PER_DAY", 10, 0, 200),
            alert_interval=integer(e, "ALERT_MIN_INTERVAL_SECONDS", 4, 3, 60),
            score=score(e, "MATCH_THRESHOLD", e.get("TIGER_CONFIDENCE") or 0.85),
            review_score=score(e, "REVIEW_SCORE", 0.65),
            max_items=integer(e, "MAX_QUEUE_ITEMS_PER_RUN", 60, 1, 500),
            queue_hours=integer(e, "MAX_QUEUE_AGE_HOURS", 72, 1, 168),
            dedup_days=integer(e, "DEDUP_RETENTION_DAYS", 90, 7, 3650),
            post_hours=integer(e, "MAX_POST_AGE_HOURS", 24, 1, 168),
            max_attempts=integer(e, "MAX_RETRY_ATTEMPTS", 6, 1, 20),
            retry_seconds=integer(e, "RETRY_BASE_SECONDS", 300, 1, 3600),
            send_photo=boolean(e, "SEND_PHOTO"), photo_sources=photo_sources, photo_media_ids=photo_ids,
            photo_rights_confirmed=boolean(e, "PHOTO_RESHARE_RIGHTS_CONFIRMED"),
            analysis_rights_confirmed=boolean(e, "AI_ANALYSIS_RIGHTS_CONFIRMED"),
            sqlite_path=e.get("SQLITE_PATH") or "tigerwatch.sqlite3",
            supabase_url=e.get("SUPABASE_URL", "").rstrip("/"),
            source_kind=(e.get("SOURCE_KIND") or "meta").lower(),
            monitor_mode=(e.get("MONITOR_MODE") or "general").lower(),
            alerts_enabled=boolean(e, "ALERTS_ENABLED", True),
            browser_posts=integer(e, "BROWSER_MAX_POSTS", 200, 1, 500),
            browser_scrolls=integer(e, "BROWSER_MAX_SCROLLS", 60, 1, 100),
            browser_delay=integer(e, "BROWSER_SCROLL_SECONDS", 3, 2, 30),
            browser_headless=boolean(e, "BROWSER_HEADLESS", True),
            daily_digest=boolean(e, "SEND_DAILY_DIGEST"),
        )
        if cfg.source_kind not in ("meta", "browser"):
            raise SetupError("SOURCE_KIND must be meta or browser")
        if cfg.source_kind == "browser" and cfg.tags:
            raise SetupError("Public-browser mode supports configured profiles only; leave HASHTAGS blank")
        cfg = cfg.with_mode(cfg.monitor_mode)
        if cfg.review_score > cfg.score:
            raise SetupError("REVIEW_SCORE must be <= MATCH_THRESHOLD")
        if not boolean(e, "FREE_TIER_ONLY", True):
            raise SetupError("This build supports free plans only; paid fallback is disabled")
        if cfg.model != "auto" and cfg.model not in FREE_MODELS:
            raise SetupError("Selected model is outside this build's verified free-tier allowlist")
        if cfg.send_photo and (not cfg.photo_rights_confirmed or not (cfg.photo_sources or cfg.photo_media_ids)):
            raise SetupError("Photo delivery needs confirmed rights and PHOTO_RESHARE_SOURCES or PHOTO_RESHARE_MEDIA_IDS")
        return cfg

    def with_mode(self, mode):
        if mode not in ("general", "sale_review", "wildlife_sales"):
            raise SetupError("MONITOR_MODE must be general, sale_review or wildlife_sales; child-safety reports are URL-only intake")
        if mode in ("sale_review", "wildlife_sales"):
            target = replace(self.target, kind="natural_language", photograph_only=True,
                             queries=tuple(replace(q, require_sale=True, photograph_only=True) for q in self.target.all_queries))
            target.validate()
            return replace(self, monitor_mode=mode, target=target, send_photo=False)
        return replace(self, monitor_mode=mode)

    @property
    def needs_sale_context(self):
        return any(q.sale_required for q in self.target.all_queries)

    @property
    def scope(self):
        return self.target.signature(self.model, self.score, self.review_score)

    def require_free(self):
        if not self.free_plans_confirmed:
            raise SetupError("Use free plans with billing disabled, then run --setup or set FREE_PLANS_CONFIRMED=true")
        if self.model != "auto" and self.model not in FREE_MODELS:
            raise SetupError("Only verified free-tier models are allowed; no paid fallback")
        if os.getenv("GITHUB_ACTIONS") == "true" and os.getenv("GITHUB_REPOSITORY_VISIBILITY") != "public":
            raise SetupError("Free cloud monitoring requires a public repository and standard GitHub runner")
        self.target.validate()

    def require(self, *names):
        missing = [n for n in names if not os.getenv(n) or os.getenv(n) == "REPLACE_ME"]
        if missing:
            raise SetupError("Missing configuration: " + ", ".join(missing))

    def require_monitor(self):
        self.require_free()
        self.require("GEMINI_API_KEY")
        if self.source_kind == "meta":
            self.require("META_ACCESS_TOKEN", "IG_USER_ID")
        if self.alerts_enabled:
            self.require("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
        if not self.tags and not self.accounts:
            raise SetupError("Configure HASHTAGS or ACCOUNTS")
        if not self.analysis_rights_confirmed:
            raise SetupError("Review AI/provider data terms and set AI_ANALYSIS_RIGHTS_CONFIRMED=true")
        if os.getenv("GITHUB_ACTIONS") == "true" and not self.supabase_url:
            raise SetupError("GitHub Actions requires persistent Supabase state")
