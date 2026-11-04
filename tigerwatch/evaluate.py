"""Explicit, budgeted evaluation of an owner's ordinary, labeled local images.

No filename, target description, caption or pixels are returned in the report.
This assesses a labeled sample, not universal accuracy or calibrated confidence.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from .errors import ProviderError, SetupError, UnsafeMedia
from .media import IMAGE_LIMIT, normalize
from .services import classify, select_model

MANIFEST_LIMIT = 200_000
BATCH_LIMIT = 32_000_000


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _no_symlinks(path):
    current = path.absolute()
    return not any(p.is_symlink() for p in (current, *current.parents))


def _examples(path, ids):
    manifest = Path(path)
    try:
        if not _no_symlinks(manifest) or not manifest.is_file():
            raise ValueError
        with manifest.open("rb") as stream:
            raw = stream.read(MANIFEST_LIMIT + 1)
        if len(raw) > MANIFEST_LIMIT:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or set(value) != {"examples"}:
            raise ValueError
        examples = value["examples"]
        if not isinstance(examples, list) or not 1 <= len(examples) <= 100:
            raise ValueError
        base = manifest.parent.resolve()
        validated = []
        for item in examples:
            if not isinstance(item, dict) or set(item) != {"path", "expected"}:
                raise ValueError
            name, expected = item["path"], item["expected"]
            if (not isinstance(name, str) or not name or len(name) > 1024
                    or "\\" in name or ":" in name or "\x00" in name):
                raise ValueError
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError
            local = base / relative
            if (not _no_symlinks(local) or not local.resolve().is_relative_to(base)
                    or not local.is_file() or local.suffix.casefold() not in (".jpg", ".jpeg", ".png", ".webp")):
                raise ValueError
            if not isinstance(expected, dict) or set(expected) != set(ids) or any(type(x) is not bool for x in expected.values()):
                raise ValueError
            validated.append((local, expected))
        # Decode the whole bounded batch before spending quota on any example.
        prepared, size = [], 0
        for local, expected in validated:
            with local.open("rb") as stream:
                jpg = normalize(stream.read(IMAGE_LIMIT + 1))
            size += len(jpg)
            if size > BATCH_LIMIT:
                raise ValueError
            prepared.append((jpg, expected))
        return prepared
    except (ValueError, TypeError, KeyError, RecursionError, OSError, UnsafeMedia):
        raise SetupError("evaluation:invalid_manifest_or_image; use ordinary local images inside the manifest directory") from None


def _outcomes(answer, cfg, ids):
    """Validate even injected adapters before scoring; abstentions stay separate."""
    try:
        detections, accepted = answer["detections"], answer["accepted"]
        if not isinstance(detections, list) or not isinstance(accepted, list):
            raise ValueError
        rows = {row["id"]: row for row in detections}
        if len(rows) != len(detections) or set(rows) != set(ids):
            raise ValueError
        accepted_ids = {row["id"] for row in accepted}
        if len(accepted_ids) != len(accepted) or not accepted_ids <= set(ids):
            raise ValueError
        outcomes = {}
        for i, ident in enumerate(ids):
            row = rows[ident]
            score = row["confidence"]
            if (type(row["allowed"]) is not bool or type(row["match"]) is not bool
                    or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1
                    or row["support"] not in ("supported", "uncertain", "needs_video", "unsupported")):
                raise ValueError
            if not row["allowed"] or row["support"] == "unsupported":
                outcomes[ident] = "unsupported"
            elif row["support"] in ("uncertain", "needs_video"):
                outcomes[ident] = row["support"]
            else:
                query = cfg.target.all_queries[i]
                threshold = cfg.score if query.threshold is None else query.threshold
                if ident in accepted_ids:
                    if not row["match"] or score < threshold:
                        raise ValueError
                    outcomes[ident] = "positive"
                elif row["match"] and min(cfg.review_score, threshold) <= score < threshold:
                    outcomes[ident] = "uncertain"
                elif query.sale_required and row.get("sale_intent") == "uncertain":
                    outcomes[ident] = "uncertain"
                else:
                    outcomes[ident] = "negative"
        return outcomes
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ProviderError("gemini", "invalid_evaluation_result") from None


def evaluate_manifest(cfg, state, http, path, *, classifier=classify, sleep=time.sleep, clock=time.monotonic):
    """Evaluate once, reserving shared AI quota for every attempted live request.

    Callers write the returned report using cases.private_json. Explicitly invoke
    only on licensed, ordinary images; never create suspected-abuse image datasets.
    """
    cfg.target.validate()
    cfg.require_free()
    cfg.require("GEMINI_API_KEY")
    if not cfg.analysis_rights_confirmed:
        raise SetupError("evaluation:analysis_rights_required")
    ids = ["q" + str(i) for i in range(1, len(cfg.target.all_queries) + 1)]
    examples = _examples(path, ids)
    counters = {ident: {"tp": 0, "fp": 0, "tn": 0, "fn": 0,
                        "uncertain": 0, "unsupported": 0, "needs_video": 0} for ident in ids}
    report = {"kind": "labeled_sample_evaluation", "model": select_model(cfg), "state_scope": cfg.scope,
              "scores_are_calibrated": False, "sample_count": len(examples), "attempted": 0,
              "evaluated": 0, "skipped": 0, "queries": counters, "examples": [],
              "limitations": ["Results describe this labeled sample only; they do not establish universal accuracy.",
                              "Abstentions and failed/skipped examples are excluded from confusion counts.",
                              "Sale intent is evaluated from image pixels only, without caption context."]}
    stop_reason, started = None, clock()
    for index, (jpg, expected) in enumerate(examples, 1):
        cooldown = getattr(state, "kv_get", lambda key: None)("cooldown/gemini")
        now = getattr(state, "clock", time.time)()
        if type(cooldown) in (int, float) and cooldown > now:
            stop_reason = stop_reason or "provider_cooldown"
        if clock() - started >= max(0, cfg.max_runtime - 80):
            stop_reason = "runtime_budget"
        if stop_reason or report["attempted"] >= cfg.ai_run:
            report["skipped"] += 1
            report["examples"].append({"index": index, "status": "skipped", "code": stop_reason or "run_budget"})
            continue
        budget = state.reserve("ai", cfg.ai_day, cfg.ai_interval)
        if not budget["ok"] and budget["reason"] == "pace" and 0 < budget["wait"] < 60:
            sleep(min(60, budget["wait"] + 0.01))
            budget = state.reserve("ai", cfg.ai_day, cfg.ai_interval)
        if not budget["ok"]:
            stop_reason = "daily_budget" if budget["reason"] == "daily" else "pacing"
            report["skipped"] += 1
            report["examples"].append({"index": index, "status": "skipped", "code": stop_reason})
            continue
        report["attempted"] += 1
        try:
            answer = classifier(http, cfg, jpg)
            outcomes = _outcomes(answer, cfg, ids)
        except ProviderError as exc:
            code = str(exc) if re.fullmatch(r"[a-z_]+:[a-z0-9_]+", str(exc)) else "provider:failure"
            report["examples"].append({"index": index, "status": "failed", "code": code})
            if exc.stop:
                stop_reason = "provider_paused"
                state.kv_set("cooldown/gemini", now + max(exc.wait, cfg.retry_seconds))
            continue
        report["evaluated"] += 1
        report["examples"].append({"index": index, "status": "evaluated", "outcomes": outcomes})
        for ident, outcome in outcomes.items():
            if outcome not in ("positive", "negative"):
                counters[ident][outcome] += 1
            else:
                key = ("tp" if expected[ident] else "fp") if outcome == "positive" else ("fn" if expected[ident] else "tn")
                counters[ident][key] += 1
    for row in counters.values():
        row["precision"] = row["tp"] / (row["tp"] + row["fp"]) if row["tp"] + row["fp"] else None
        row["recall"] = row["tp"] / (row["tp"] + row["fn"]) if row["tp"] + row["fn"] else None
        row["decision_coverage"] = sum(row[key] for key in ("tp", "fp", "tn", "fn")) / report["evaluated"] if report["evaluated"] else None
    report["failed"] = report["attempted"] - report["evaluated"]
    return report
