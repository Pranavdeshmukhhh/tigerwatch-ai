"""Exact-image reuse saves model calls without reusing context-dependent evidence."""
import hashlib
from dataclasses import replace

import pytest

from tigerwatch.cache import assessment
from tigerwatch.media import normalize
from tigerwatch.targets import Target
from .fakes import Response, decision, gemini_response, jpeg, post


def cached_decision(cfg):
    rows = decision()["targets"]
    return {"match": True, "allowed_target": True, "real_photo": True, "confidence": 0.97,
            "detections": rows, "accepted": rows, "review": False, "needs_video": False,
            "model": cfg.model, "review_only": False}


def image_key():
    return hashlib.sha256(normalize(jpeg())).hexdigest()


def test_identical_photos_reuse_assessment_but_keep_each_source_reference(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, alerts_enabled=False)
    p.http.posts = [post("1001"), post("1002")]
    metrics = p.run()
    assert metrics["ai_attempts"] == metrics["cache_hits"] == 1
    assert p.http.count("generateContent") == 1
    assert p.state.stats()["today"]["ai"] == 1
    rows = [p.state.inspect(x) for x in ("1001", "1002")]
    assert all(x["status"] == "review" for x in rows)
    assert {x["result"]["source_link"] for x in rows} == {x["permalink"] for x in p.http.posts}
    assert sum(x["result"]["assessment_reused"] for x in rows) == 1
    entry = p.state.cache_get(image_key())
    assert "cdninstagram" not in str(entry) and "instagram.com" not in str(entry)


def test_cache_hit_survives_ai_caps_and_gemini_cooldown(pipeline):
    p = pipeline
    p.state.cache_put(image_key(), cached_decision(p.cfg))
    p.state.kv_set("cooldown/gemini", p.clock() + 3600)
    p.cfg = replace(p.cfg, ai_run=0, ai_day=0, alerts_enabled=False)
    metrics = p.run()
    assert p.state.inspect("1001")["status"] == "review"
    assert metrics["cache_hits"] == 1 and p.http.count("generateContent") == 0
    assert p.state.stats()["today"].get("ai", 0) == 0


def test_concurrent_identical_assessment_defers_without_ai(pipeline):
    p = pipeline
    assert p.state.cache_claim(image_key(), "other-worker", lease=180)["status"] == "claimed"
    metrics = p.run()
    row = p.state.inspect("1001")
    assert metrics["cache_busy"] == 1 and row["status"] == "retry" and row["attempts"] == 0
    assert row["last_error"] == "cache_assessment_in_progress"
    assert p.http.count("generateContent") == 0
    assert p.state.cache_release(image_key(), "other-worker")
    p.clock.sleep(181)
    p.run()
    assert p.http.count("generateContent") == 1


def test_model_outage_releases_cache_claim(pipeline):
    p = pipeline
    p.http.gemini = [Response({}, 503)]
    p.run()
    assert p.state.inspect("1001")["status"] == "retry"
    assert p.state.cache_claim(image_key(), "next-worker", lease=180)["status"] == "claimed"


def test_corrupt_cache_is_invalidated_before_fresh_assessment(pipeline):
    p = pipeline
    p.state.cache_put(image_key(), {"match": True, "untrusted_text": "must never become evidence"})
    metrics = p.run()
    assert metrics["invalid_cache_entries"] == 1
    assert p.http.count("generateContent") == 1
    assert p.state.inspect("1001")["status"] == "alerted"
    assert "untrusted_text" not in p.state.cache_get(image_key())


def test_different_pixels_are_never_fuzzy_reused(pipeline):
    p = pipeline
    p.http.posts = [post("1001"), post("1002")]
    p.http.images[post("1002")["media_url"]] = Response(headers={"Content-Type": "image/jpeg"}, content=jpeg("blue"))
    p.run()
    assert p.http.count("generateContent") == 2


def test_changed_target_does_not_reuse_another_scope(pipeline):
    p = pipeline
    p.run()
    p.cfg = replace(p.cfg, target=Target("natural_language", "a red car", False))
    p.run()
    assert p.http.count("generateContent") == 2


def test_sale_context_always_gets_fresh_assessment(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, alerts_enabled=False).with_mode("wildlife_sales")
    p.http.posts = [post("1001", caption="for sale"), post("1002", caption="museum educational display")]
    body = decision()
    body["targets"][0]["sale_intent"] = "yes"
    p.http.gemini = [Response(gemini_response(body))]
    p.run()
    assert p.http.count("generateContent") == 2
    assert p.worker.metrics["cache_hits"] == 0
    assert p.state.inspect("1001")["status"] == "review"
    assert p.state.inspect("1002")["status"] == "rejected"


@pytest.mark.parametrize("change", [
    {"match": False}, {"confidence": True}, {"confidence": float("nan")},
    {"allowed_target": False}, {"review_only": True}, {"model": "another-model"},
    {"accepted": []}, {"review": True}, {"real_photo": 1},
    {"detections": [{"id": "q1", "allowed": True, "match": True, "confidence": .97,
                     "support": "supported", "boxes": [[0, 0, 1001, 1001]]}]},
])
def test_cache_revalidates_model_flags_scores_boxes_and_aggregates(pipeline, change):
    with pytest.raises(ValueError):
        assessment(pipeline.cfg, {**cached_decision(pipeline.cfg), **change})
