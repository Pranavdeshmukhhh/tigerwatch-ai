"""Deterministic, editable watch interpretation; never claims invisible semantics."""
from __future__ import annotations

from dataclasses import replace
import math

from .errors import SetupError
from .services import select_model
from .targets import Query, Target, plan_query
from .watches import profile_handle

FIELDS = {"profiles", "targets", "source", "mode", "exclusions", "threshold", "photograph_only"}


def config_from_rules(cfg, payload):
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        raise SetupError("Use profiles, targets, source, mode, exclusions, threshold and photograph_only only")
    profiles, descriptions = payload.get("profiles"), payload.get("targets")
    if not isinstance(profiles, list) or not 1 <= len(profiles) <= 20:
        raise SetupError("Choose 1–20 authorized Instagram profiles")
    profiles = tuple(dict.fromkeys(profile_handle(x) for x in profiles))
    if not isinstance(descriptions, list) or not 1 <= len(descriptions) <= 10:
        raise SetupError("Enter 1–10 target descriptions")
    if any(not isinstance(x, str) or not x.strip() or len(x) > 300 for x in descriptions):
        raise SetupError("Each description must contain 1–300 characters")
    # Validate before composing exclusions, so prohibited requests cannot be hidden.
    Target("natural_language", descriptions[0], False, tuple(Query(x) for x in descriptions)).validate()
    exclusions = payload.get("exclusions", [])
    if (not isinstance(exclusions, list) or len(exclusions) > 5
            or any(not isinstance(x, str) or not x.strip() or len(x) > 100 for x in exclusions)):
        raise SetupError("Use up to five short visual exclusions")
    threshold = payload.get("threshold", cfg.score)
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise SetupError("Threshold must be between 0 and 1")
    photograph = payload.get("photograph_only", False)
    if type(photograph) is not bool:
        raise SetupError("photograph_only must be a boolean")
    source, mode = payload.get("source", "browser"), payload.get("mode", "general")
    if source not in ("browser", "meta"):
        raise SetupError("Choose browser or meta source")
    suffix = "; exclude: " + "; ".join(x.strip() for x in exclusions) if exclusions else ""
    queries = tuple(Query(x.strip() + suffix, threshold, photograph) for x in descriptions)
    target = Target("natural_language", queries[0].description, False, queries).validate()
    return replace(cfg, accounts=profiles, tags=(), target=target, model="auto", source_kind=source).with_mode(mode)


def watch_value(cfg):
    return {"version": 1, "source": cfg.source_kind, "mode": cfg.monitor_mode,
            "profiles": list(cfg.accounts), "targets": [
                {"description": q.description, "threshold": q.threshold,
                 "photograph_only": q.photograph_only, "require_sale": q.require_sale}
                for q in cfg.target.all_queries]}


def preview_rules(cfg, payload):
    chosen = config_from_rules(cfg, payload)
    rules = [{"description": q.description, "threshold": q.threshold,
              "require_sale": q.sale_required, "photograph_only": q.photograph_only,
              **plan_query(q.description)} for q in chosen.target.all_queries]
    return {"watch": watch_value(chosen), "rules": rules, "selected_model": select_model(chosen),
            "scope": chosen.scope, "network_calls": 0,
            "limitations": ["Preview uses explicit rules and keyword hints; it is not AI interpretation or retraining.",
                            "Scores are uncalibrated. Free quotas and source visibility can stop processing.",
                            "No face/name identification, precise masks or live Instagram video tracking.",
                            "Sale candidates need human review; authenticity and legality are unverified."]}
