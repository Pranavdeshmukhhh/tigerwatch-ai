"""Strict validation for reusable general still-image assessments.

Only a SHA-256 of normalized image bytes and validated bounded model output are
cached. Scope is supplied by State; captions, URLs, photos and sale context are
never cached here. Derived flags are recomputed rather than trusted from storage.
"""
from __future__ import annotations

import math

from .services import select_model
from .targets import plan_query

FIELDS = {"match", "allowed_target", "real_photo", "confidence", "detections", "accepted",
          "review", "needs_video", "model", "review_only"}
DETECTION = {"id", "allowed", "match", "confidence", "support", "boxes"}


def assessment(cfg, value):
    """Return a canonical copy, or raise ValueError for an unsafe/stale contract."""
    if cfg.needs_sale_context or not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("invalid cache contract")
    for field in ("match", "allowed_target", "real_photo", "review", "needs_video", "review_only"):
        if type(value[field]) is not bool:
            raise ValueError("invalid cache flag")
    if value["model"] != select_model(cfg) or value["review_only"]:
        raise ValueError("incompatible cache model or context")
    rows = value["detections"]
    queries = cfg.target.all_queries
    if not isinstance(rows, list) or len(rows) != len(queries):
        raise ValueError("invalid cached query set")
    expected = {"q" + str(i) for i in range(1, len(queries) + 1)}
    seen, detections, accepted, review = set(), [], [], False
    for row in rows:
        if not isinstance(row, dict) or set(row) != DETECTION:
            raise ValueError("invalid cached detection")
        ident = row["id"]
        if not isinstance(ident, str) or ident not in expected or ident in seen:
            raise ValueError("invalid cached query ID")
        seen.add(ident)
        if type(row["allowed"]) is not bool or type(row["match"]) is not bool:
            raise ValueError("invalid cached decision flag")
        score = row["confidence"]
        if type(score) not in (float, int) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("invalid cached score")
        if row["support"] not in ("supported", "uncertain", "needs_video", "unsupported"):
            raise ValueError("invalid cached support")
        boxes = row["boxes"]
        if not isinstance(boxes, list) or len(boxes) > 5:
            raise ValueError("invalid cached boxes")
        for box in boxes:
            if (not isinstance(box, list) or len(box) != 4 or
                    any(type(x) is not int or not 0 <= x <= 1000 for x in box) or
                    box[0] >= box[2] or box[1] >= box[3]):
                raise ValueError("invalid cached box")
        query = queries[int(ident[1:]) - 1]
        plan = plan_query(query.description)
        if (not plan["supported"] and (row["support"] != "unsupported" or row["match"] or boxes)):
            raise ValueError("cached capability mismatch")
        if (plan["supported"] and plan["requires_video"] and
                (row["support"] != "needs_video" or row["match"] or boxes)):
            raise ValueError("cached frame-context mismatch")
        canonical = {**row, "boxes": [list(x) for x in boxes]}
        photo_only = cfg.target.photograph_only if query.photograph_only is None else query.photograph_only
        eligible = row["allowed"] and row["support"] == "supported" and row["match"] and (not photo_only or value["real_photo"])
        threshold = cfg.score if query.threshold is None else query.threshold
        if eligible and score >= threshold:
            accepted.append(canonical)
        elif (eligible and score >= min(cfg.review_score, threshold)) or row["support"] == "uncertain":
            review = True
        detections.append(canonical)
    result = {"match": bool(accepted),
              "allowed_target": any(x["allowed"] and x["support"] != "unsupported" for x in detections),
              "real_photo": value["real_photo"],
              "confidence": max((x["confidence"] for x in accepted or detections), default=0),
              "detections": detections, "accepted": accepted, "review": review,
              "needs_video": any(x["support"] == "needs_video" for x in detections),
              "model": select_model(cfg), "review_only": False}
    if type(value["confidence"]) not in (int, float) or value != result:
        raise ValueError("inconsistent cached aggregates")
    return result
