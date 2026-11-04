"""Small private watch definitions; no credentials in these JSON files."""
from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace

from .cases import private_json
from .config import csv
from .errors import SetupError
from .net import secure_url
from .targets import Query, Target, target_from_env


def profile_handle(value):
    import re
    if not isinstance(value, str):
        raise SetupError("Invalid Instagram profile")
    value = value.strip()
    if value.startswith("https://"):
        p = secure_url(value)
        if not p or p.hostname not in ("instagram.com", "www.instagram.com") or p.query:
            raise SetupError("Use an Instagram username or HTTPS profile URL without query/credentials")
        value = p.path.strip("/")
    value = value.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", value) or value.casefold() in {"accounts", "challenge", "checkpoint", "explore", "direct", "p", "reel", "reels"}:
        raise SetupError("Use a valid Instagram username")
    return value.casefold()


def load_watch(path, cfg):
    path = Path(path)
    if path.stat().st_size > 32_000:
        raise SetupError("Watch file exceeds 32 KB")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or set(value) != {"version", "source", "mode", "profiles", "targets"}
                or value["version"] != 1 or value["source"] not in ("meta", "browser")
                or not isinstance(value["profiles"], list) or not 1 <= len(value["profiles"]) <= 20):
            raise ValueError
        profiles = tuple(dict.fromkeys(profile_handle(x) for x in value["profiles"]))
        from .config import boolean
        target = target_from_env({"TARGETS_JSON": json.dumps(value["targets"])}, boolean)
        return replace(cfg, accounts=profiles, tags=(), source_kind=value["source"], target=target,
                       model="auto").with_mode(value["mode"])
    except (ValueError, KeyError, TypeError, RecursionError):
        raise SetupError("Invalid watch file; use --configure-watch") from None


def save_watch(path, cfg):
    if not cfg.accounts:
        raise SetupError("A profile watch needs at least one Instagram account")
    cfg.target.validate()
    private_json(path, {"version": 1, "source": cfg.source_kind, "mode": cfg.monitor_mode,
                        "profiles": list(cfg.accounts), "targets": [
                            {"description": q.description, "threshold": q.threshold,
                             "photograph_only": q.photograph_only, "require_sale": q.require_sale}
                            for q in cfg.target.all_queries]})


def configure_watch(path, cfg, *, ask=input):
    profiles = tuple(profile_handle(x) for x in csv(ask("Instagram profiles, comma-separated: ")))
    text = ask("Describe targets (separate multiple descriptions with ;): ").strip()
    queries = tuple(Query(x.strip()) for x in text.split(";") if x.strip())
    if not queries:
        raise SetupError("Enter at least one visual target")
    mode = ask("Mode [general / sale_review / wildlife_sales] (default general): ").strip() or "general"
    source = ask("Source [browser / meta] (default browser): ").strip() or "browser"
    if source not in ("browser", "meta"):
        raise SetupError("Choose browser or meta")
    target = Target("natural_language", queries[0].description, False, queries).validate()
    chosen = replace(cfg, accounts=profiles, tags=(), source_kind=source, target=target, model="auto").with_mode(mode)
    save_watch(path, chosen)
    return chosen
