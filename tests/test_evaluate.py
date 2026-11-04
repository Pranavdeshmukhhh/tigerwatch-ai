import json
from dataclasses import replace

import pytest

from tigerwatch.errors import ProviderError, SetupError
from tigerwatch.evaluate import evaluate_manifest
from tigerwatch.targets import Target
from .fakes import jpeg


def manifest(tmp_path, labels):
    rows = []
    for i, expected in enumerate(labels):
        name = f"private-location-{i}.jpg"
        (tmp_path / name).write_bytes(jpeg())
        rows.append({"path": name, "expected": expected})
    path = tmp_path / "examples.json"
    path.write_text(json.dumps({"examples": rows}))
    return path


def answer(positive=True, *, support="supported", allowed=True, score=0.95):
    row = {"id": "q1", "allowed": allowed, "match": positive, "confidence": score,
           "support": support, "boxes": []}
    return {"detections": [row], "accepted": [row] if positive and support == "supported" and allowed and score >= 0.85 else []}


def config(p):
    return replace(p.cfg, analysis_rights_confirmed=True, ai_run=100)


def test_confusion_counts_precision_and_privacy(pipeline, tmp_path):
    p = pipeline
    path = manifest(tmp_path, [{"q1": True}, {"q1": False}, {"q1": True}, {"q1": False}])
    replies = iter([answer(True), answer(True), answer(False), answer(False)])
    calls = []
    def classify(http, cfg, image):
        calls.append(image)
        return next(replies)
    report = evaluate_manifest(config(p), p.state, p.http, path, classifier=classify, sleep=p.clock.sleep)
    q = report["queries"]["q1"]
    assert [q[k] for k in ("tp", "fp", "tn", "fn")] == [1, 1, 1, 1]
    assert q["precision"] == q["recall"] == 0.5 and q["decision_coverage"] == 1
    assert report["attempted"] == report["evaluated"] == len(calls) == 4
    assert p.state.stats()["today"]["ai"] == 4
    assert "private-location" not in json.dumps(report) and p.cfg.target.description not in json.dumps(report)
    assert not report["scores_are_calibrated"]


@pytest.mark.parametrize("support,allowed,bucket", [("uncertain", True, "uncertain"),
                                                   ("needs_video", True, "needs_video"),
                                                   ("unsupported", True, "unsupported"),
                                                   ("supported", False, "unsupported")])
def test_abstentions_do_not_become_false_negatives(pipeline, tmp_path, support, allowed, bucket):
    p = pipeline
    path = manifest(tmp_path, [{"q1": True}])
    report = evaluate_manifest(config(p), p.state, p.http, path,
                               classifier=lambda *a: answer(False, support=support, allowed=allowed))
    q = report["queries"]["q1"]
    assert q[bucket] == 1 and q["fn"] == 0
    assert q["precision"] is q["recall"] is None and q["decision_coverage"] == 0


def test_borderline_score_is_abstention(pipeline, tmp_path):
    p = pipeline
    report = evaluate_manifest(config(p), p.state, p.http, manifest(tmp_path, [{"q1": True}]),
                               classifier=lambda *a: answer(True, score=0.75))
    assert report["queries"]["q1"]["uncertain"] == 1


@pytest.mark.parametrize("bad_path", ["../outside.jpg", "https://evil.test/a.jpg", "/etc/passwd", "C:\\private.jpg"])
def test_untrusted_paths_fail_before_any_calls(pipeline, tmp_path, bad_path):
    p = pipeline
    path = tmp_path / "examples.json"
    path.write_text(json.dumps({"examples": [{"path": bad_path, "expected": {"q1": True}}]}))
    with pytest.raises(SetupError, match="invalid_manifest"):
        evaluate_manifest(config(p), p.state, p.http, path, classifier=lambda *a: pytest.fail("AI invoked"))
    assert p.state.stats()["today"] == {}


def test_entire_batch_validated_before_first_ai_call(pipeline, tmp_path):
    p = pipeline
    path = manifest(tmp_path, [{"q1": True}, {"q1": False}])
    (tmp_path / "private-location-1.jpg").write_bytes(b"not an image")
    with pytest.raises(SetupError):
        evaluate_manifest(config(p), p.state, p.http, path, classifier=lambda *a: pytest.fail("AI invoked"))
    assert p.state.stats()["today"] == {}


def test_symlink_image_refused(pipeline, tmp_path):
    p = pipeline
    path = manifest(tmp_path, [{"q1": True}])
    original = tmp_path / "private-location-0.jpg"
    replacement = tmp_path / "original.jpg"
    original.rename(replacement)
    try:
        original.symlink_to(replacement)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    with pytest.raises(SetupError):
        evaluate_manifest(config(p), p.state, p.http, path)
    assert not p.http.calls


@pytest.mark.parametrize("payload", [{"examples": []}, {"examples": [{"path": "x.jpg", "expected": {"q1": 1}}]},
                                      {"examples": [], "upload": True}, {"examples": [None]}])
def test_invalid_manifest_schema_refused(pipeline, tmp_path, payload):
    path = tmp_path / "examples.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(SetupError):
        evaluate_manifest(config(pipeline), pipeline.state, pipeline.http, path)
    assert not pipeline.http.calls


def test_duplicate_json_keys_refused(pipeline, tmp_path):
    path = tmp_path / "examples.json"
    path.write_text('{"examples":[],"examples":[]}')
    with pytest.raises(SetupError):
        evaluate_manifest(config(pipeline), pipeline.state, pipeline.http, path)


def test_daily_and_run_budgets_pause_remaining_examples(pipeline, tmp_path):
    p = pipeline
    path = manifest(tmp_path, [{"q1": True}] * 3)
    report = evaluate_manifest(replace(config(p), ai_day=1), p.state, p.http, path,
                               classifier=lambda *a: answer(), sleep=p.clock.sleep)
    assert report["attempted"] == 1 and report["skipped"] == 2
    assert all(x["code"] == "daily_budget" for x in report["examples"][1:])
    report = evaluate_manifest(replace(config(p), ai_run=0), p.state, p.http, path,
                               classifier=lambda *a: pytest.fail("AI invoked"))
    assert report["attempted"] == 0 and report["skipped"] == 3


def test_provider_auth_pause_and_safe_failure_code(pipeline, tmp_path):
    p = pipeline
    path = manifest(tmp_path, [{"q1": True}] * 2)
    def classify(*args):
        raise ProviderError("gemini", "authentication", stop=True)
    report = evaluate_manifest(config(p), p.state, p.http, path, classifier=classify)
    assert report["failed"] == 1 and report["skipped"] == 1
    assert report["examples"][0]["code"] == "gemini:authentication"
    assert report["queries"]["q1"]["fn"] == 0


def test_unsafe_target_refused_before_reading_dataset(pipeline):
    p = pipeline
    cfg = replace(config(p), target=Target("natural_language", "CSAM", False))
    with pytest.raises(SetupError, match="report-url"):
        evaluate_manifest(cfg, p.state, p.http, "/missing.json")
    assert not p.http.calls


def test_missing_processing_rights_refused(pipeline, tmp_path):
    p = pipeline
    with pytest.raises(SetupError, match="analysis_rights"):
        evaluate_manifest(replace(config(p), analysis_rights_confirmed=False), p.state, p.http,
                          manifest(tmp_path, [{"q1": True}]))


def test_malformed_adapter_result_cannot_manufacture_metrics(pipeline, tmp_path):
    p = pipeline
    report = evaluate_manifest(config(p), p.state, p.http, manifest(tmp_path, [{"q1": True}]),
                               classifier=lambda *a: {"detections": [], "accepted": []})
    assert report["failed"] == 1 and report["evaluated"] == 0
    assert report["queries"]["q1"]["fn"] == 0


def test_long_pacing_defers_without_blocking_sleep(pipeline, tmp_path):
    class Budget:
        def reserve(self, *a):
            return {"ok": False, "reason": "pace", "wait": 60}
    report = evaluate_manifest(config(pipeline), Budget(), pipeline.http, manifest(tmp_path, [{"q1": True}]),
                               sleep=lambda *a: pytest.fail("Blocked for 60s"))
    assert report["skipped"] == 1


def test_active_provider_cooldown_does_not_spend_quota(pipeline, tmp_path):
    p = pipeline
    p.state.kv_set("cooldown/gemini", p.clock() + 300)
    report = evaluate_manifest(config(p), p.state, p.http, manifest(tmp_path, [{"q1": True}]),
                               classifier=lambda *a: pytest.fail("Ignored provider cooldown"))
    assert report["skipped"] == 1 and report["examples"][0]["code"] == "provider_cooldown"
    assert not p.state.stats()["today"]
