import json
from dataclasses import replace

import pytest

from tigerwatch.config import Config
from tigerwatch.errors import SetupError
from tigerwatch.services import classify
from tigerwatch.store import State
from tigerwatch.targets import Query, Target, plan_query
from tigerwatch.video import SessionTracker, overlap, run_video
from .fakes import Response, decision, gemini_response, jpeg, post


def target_config(pipeline, *queries):
    return replace(pipeline.cfg, target=Target("natural_language", queries[0], False, tuple(Query(x) for x in queries)))


def result(ident="q1", *, score=0.97, matched=True, allowed=True, support="supported", box=None):
    return {"id": ident, "allowed": allowed, "match": matched, "confidence": score,
            "support": support, "boxes": [box or [100, 100, 600, 600]] if matched else []}


def response(*results, real=True):
    return Response(gemini_response({"real_photo": real, "targets": list(results)}))


@pytest.mark.parametrize("description", ["Pikachu", "an elephant", "a red car", "a person wearing a blue shirt",
                                       "a round green product", 'a sign that reads "STOP"'])
def test_arbitrary_natural_language_without_category(description):
    cfg = Config.from_env({"TARGET_DESCRIPTION": description})
    assert cfg.target.kind == "natural_language"
    assert cfg.target.all_queries[0].description == description


def test_multiple_targets_one_image_one_model_call(pipeline):
    p = pipeline
    p.cfg = target_config(p, "Pikachu", "a red car", 'text saying "STOP"')
    p.http.gemini = [response(result("q1", matched=False), result("q2"), result("q3", score=0.88))]
    p.run()
    assert p.http.count("generateContent") == 1
    assert p.state.inspect("1001")["status"] == "alerted"
    assert {x["id"] for x in p.state.inspect("1001")["result"]["detections"]} == {"q2", "q3"}
    message = p.http.sent[0]["json"]["text"]
    assert "a red car" in message and "Pikachu" not in message


def test_fictional_art_can_match_without_photograph_requirement(pipeline):
    p = pipeline
    p.cfg = target_config(p, "Pikachu")
    p.http.gemini = [response(result(), real=False)]
    p.run()
    assert p.state.inspect("1001")["status"] == "alerted"


def test_per_query_threshold_is_used(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, target=Target("natural_language", "a blue square", False, (Query("a blue square", 0.7),)))
    p.http.gemini = [response(result(score=0.75))]
    p.run()
    assert p.state.inspect("1001")["status"] == "alerted"


def test_target_change_isolated_but_daily_usage_shared(pipeline):
    p = pipeline
    p.http.gemini = [Response(gemini_response(decision(False)))]
    p.run()
    old_scope = p.cfg.scope
    assert p.state.inspect("1001")["status"] == "rejected"
    p.cfg = target_config(p, "Pikachu")
    p.http.gemini = [response(result())]
    p.clock.sleep(10)
    p.run()
    assert p.cfg.scope != old_scope
    assert p.state.inspect("1001")["status"] == "alerted"
    assert p.state.stats()["today"]["ai"] == 2
    assert p.state.db.execute("SELECT count(*) FROM tigerwatch_queue").fetchone()[0] == 2


def test_target_scope_changes_with_threshold(pipeline):
    assert pipeline.cfg.scope != replace(pipeline.cfg, score=0.99).scope


def test_cross_target_claim_cannot_consume_other_target_work(pipeline):
    p = pipeline
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": post()}])
    other = State(target_config(p, "a red car"), p.http, clock=p.clock)
    try:
        assert other.claim() is None
        assert other.stats()["queue"] == {}
    finally:
        other.close()


def test_motion_cannot_be_confirmed_from_a_still_image(pipeline):
    p = pipeline
    p.cfg = target_config(p, "a moving vehicle")
    p.http.gemini = [response(result())]
    p.run()
    assert p.state.inspect("1001")["status"] == "review"
    assert p.http.count("sendMessage") == 0


def test_motion_query_uses_ordered_video_context(pipeline):
    p = pipeline
    cfg = target_config(p, "a moving vehicle")
    p.http.gemini = [response(result())]
    answer = classify(p.http, cfg, jpeg(), frames=[jpeg(), jpeg(), jpeg()])
    assert answer["match"]
    assert len(p.http.ai_payloads[0]["contents"][0]["parts"]) == 4


def test_unsupported_segmentation_is_not_invented(pipeline):
    p = pipeline
    cfg = target_config(p, "precise segmentation masks for every car")
    p.http.gemini = [response(result())]
    answer = classify(p.http, cfg, jpeg())
    assert not answer["match"] and not answer["allowed_target"]
    assert not plan_query(cfg.target.description)["supported"]


def test_human_identity_denial_does_not_alert(pipeline):
    p = pipeline
    p.cfg = target_config(p, "a named real person")
    with pytest.raises(SetupError):
        p.cfg.target.validate()


def test_named_human_rejected_by_semantic_safety_result(pipeline):
    p = pipeline
    p.cfg = target_config(p, "a specific celebrity")
    p.http.gemini = [response(result(allowed=False, matched=False, support="unsupported"))]
    p.run()
    assert p.state.inspect("1001")["status"] == "unsupported"
    assert p.http.count("sendMessage") == 0


@pytest.mark.parametrize("key", ["FACE_IMAGE", "REFERENCE_FACE", "PERSON_NAME", "REFERENCE_IMAGE"])
def test_reference_face_or_identity_configuration_is_unavailable(key):
    with pytest.raises(SetupError):
        Config.from_env({key: "sample"})


def test_no_live_ai_without_free_plan_confirmation(pipeline):
    p = pipeline
    with pytest.raises(SetupError, match="free plans"):
        classify(p.http, replace(p.cfg, free_plans_confirmed=False), jpeg())
    assert not p.http.calls


@pytest.mark.parametrize("model", ["gemini-4-argon", "unknown-paid-model"])
def test_paid_or_unverified_model_is_rejected(model):
    with pytest.raises(SetupError):
        Config.from_env({"GEMINI_MODEL": model})


def test_paid_mode_cannot_be_enabled():
    with pytest.raises(SetupError):
        Config.from_env({"FREE_TIER_ONLY": "false"})


def test_private_github_runtime_is_rejected(pipeline, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY_VISIBILITY", "private")
    with pytest.raises(SetupError):
        pipeline.cfg.require_free()


@pytest.mark.parametrize("queries", ['{}', '[]', '[17]', '[{"description":17}]', '[{"description":"x","threshold":true}]', '[{"description":"x","threshold":2}]'])
def test_invalid_multi_target_configuration(queries):
    with pytest.raises(SetupError):
        Config.from_env({"TARGETS_JSON": queries})


def test_mixed_supported_and_unsupported_targets_can_still_match(pipeline):
    p = pipeline
    cfg = target_config(p, "a blue shirt", "precise segmentation masks")
    p.http.gemini = [response(result("q1"), result("q2", allowed=False, matched=False, support="unsupported"))]
    answer = classify(p.http, cfg, jpeg())
    assert answer["match"] and [x["id"] for x in answer["accepted"]] == ["q1"]


@pytest.mark.parametrize("bad_box", [[0, 0, 1], [10, 20, 5, 40], [0, 0, 1001, 1000], [False, 0, 100, 100]])
def test_untrusted_boxes_rejected(pipeline, bad_box):
    p = pipeline
    p.http.gemini = [response(result(box=bad_box))]
    from tigerwatch.errors import ProviderError
    with pytest.raises(ProviderError):
        classify(p.http, p.cfg, jpeg())


def test_session_tracker_reuses_overlap_but_never_cross_target_identity():
    tracker = SessionTracker()
    first = tracker.update([result("q1")])[0]
    second = tracker.update([result("q1", box=[110, 110, 610, 610])])[0]
    third = tracker.update([result("q2", box=[110, 110, 610, 610])])[0]
    assert first["session_track"] == second["session_track"]
    assert second["relative_frame_displacement"] > 0
    assert third["session_track"] != first["session_track"]
    assert SessionTracker().update([result()])[0]["session_track"] == 1
    assert overlap([0, 0, 10, 10], [100, 100, 200, 200]) == 0


def test_local_video_decoding_with_mocked_ai_and_tracking(pipeline, tmp_path):
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    p = pipeline
    cfg = replace(target_config(p, "a moving red square"), analysis_rights_confirmed=True, ai_interval=1)
    path = tmp_path / "synthetic.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 64))
    if not writer.isOpened():
        pytest.skip("MJPG encoder unavailable on this OpenCV build")
    for i in range(6):
        frame = np.zeros((64, 64, 3), np.uint8)
        cv2.rectangle(frame, (i + 5, 15), (i + 25, 35), (0, 0, 255), -1)
        writer.write(frame)
    writer.release()
    p.http.gemini = [response(result())]
    output = []
    summary = run_video(cfg, p.state, p.http, str(path), interval=1, max_samples=4,
                        clock=p.clock, sleep=p.clock.sleep, emit=output.append)
    assessments = [json.loads(x) for x in output if json.loads(x)["event"] == "assessment"]
    assert summary["ai_attempts"] == 2 and len(assessments) == 2
    assert assessments[0]["tracks"][0]["session_track"] == assessments[1]["tracks"][0]["session_track"]
    assert p.http.count("api.telegram.org") == 0
    assert p.state.stats()["today"]["ai"] == 2


def test_video_network_url_is_rejected_without_http(pipeline):
    pytest.importorskip("cv2")
    with pytest.raises(SetupError, match="local file"):
        run_video(replace(pipeline.cfg, analysis_rights_confirmed=True), pipeline.state, pipeline.http,
                  "https://evil.example/video.mp4")
    assert not pipeline.http.calls


def test_plan_command_needs_no_credentials(monkeypatch, capsys):
    from tigerwatch.cli import main
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert main(["--plan", "--target", "a person wearing a blue shirt", "--target", "a moving vehicle"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert len(plan["queries"]) == 2 and plan["queries"][1]["requires_video"]
    assert not plan["face_identification"]


@pytest.mark.parametrize("queries,video,expected", [
    (["Pikachu"], False, "gemini-3.5-flash-lite"),
    (['a sign saying "STOP"'], False, "gemini-3.8-flash"),
    (["a blue shirt", "a red car"], False, "gemini-3.8-flash"),
    (["a red car"], True, "gemini-3.8-flash"),
])
def test_auto_model_routing_uses_only_verified_free_models(pipeline, queries, video, expected):
    from tigerwatch.services import select_model
    from tigerwatch.config import FREE_MODELS
    cfg = replace(target_config(pipeline, *queries), model="auto")
    assert select_model(cfg, video=video) == expected
    assert expected in FREE_MODELS


def test_auto_complex_request_uses_supported_low_thinking_setting(pipeline):
    p = pipeline
    cfg = replace(target_config(p, 'a sign with text "STOP"'), model="auto")
    p.http.gemini = [response(result())]
    answer = classify(p.http, cfg, jpeg())
    assert answer["model"] == "gemini-3.8-flash"
    assert p.http.ai_payloads[0]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_video_daily_budget_pauses_without_ai_call(pipeline, tmp_path):
    pytest.importorskip("cv2")
    import numpy as np
    p = pipeline
    cfg = replace(p.cfg, analysis_rights_confirmed=True, ai_day=0)
    path = tmp_path / "dummy.avi"
    path.write_bytes(b"fake capture fixture")
    class Capture:
        released = False
        def isOpened(self):
            return True
        def get(self, key):
            return 1.0
        def read(self):
            return True, np.zeros((16, 16, 3), np.uint8)
        def release(self):
            self.released = True
    capture, output = Capture(), []
    summary = run_video(cfg, p.state, p.http, str(path), interval=1, max_samples=5,
                        capture_factory=lambda _: capture, clock=p.clock, sleep=p.clock.sleep, emit=output.append)
    assert summary["ai_attempts"] == 0 and p.http.count("generateContent") == 0
    assert capture.released and json.loads(output[0])["reason"] == "ai_daily_budget"
