from dataclasses import replace

import pytest
import requests

from tigerwatch.store import State
from .fakes import Response, decision, gemini_response, jpeg, post


def test_complete_pipeline_and_duplicates(pipeline):
    p = pipeline
    p.http.posts[0]["caption"] = "PRIVATE_CAPTION_LOCATION_SENTINEL"
    p.http.posts *= 2
    p.run()
    p.run()
    assert p.state.inspect("1001")["status"] == "alerted"
    assert p.http.count("generateContent") == 1
    assert p.http.count("sendMessage") == 1
    alert = p.http.sent[0]["json"]
    assert alert["link_preview_options"] == {"is_disabled": True}
    assert "#tiger" in alert["text"] and "uncalibrated" in alert["text"]
    assert p.state.inspect("1001")["data"] == {}
    assert p.http.ai_payloads[0]["contents"][0]["parts"][1]["inlineData"]["data"]
    assert "PRIVATE_CAPTION_LOCATION_SENTINEL" not in str(p.http.ai_payloads)


@pytest.mark.parametrize("answer", [decision(False), decision(True, real=False), decision(True, score=0.2)])
def test_false_matches_are_rejected_once(pipeline, answer):
    p = pipeline
    p.http.gemini = [Response(gemini_response(answer))]
    p.run()
    p.run()
    assert p.state.inspect("1001")["status"] == "rejected"
    assert p.http.count("generateContent") == 1
    assert p.http.sent == []


def test_borderline_goes_to_human_review(pipeline):
    p = pipeline
    p.http.gemini = [Response(gemini_response(decision(score=0.75)))]
    p.run()
    assert p.state.inspect("1001")["status"] == "review"
    assert p.http.sent == []


def test_carousel_resumes_negative_children_without_reclassification(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, ai_run=1)
    p.http.posts = [post(media_type="CAROUSEL_ALBUM", children={"data": [
        {"id": "2001", "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/one.jpg"},
        {"id": "2002", "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/two.jpg"}]})]
    # Distinct scenes must have distinct pixels now exact-byte results are reused.
    p.http.images["https://scontent.cdninstagram.com/two.jpg"] = Response(
        headers={"Content-Type": "image/jpeg"}, content=jpeg("blue"))
    p.http.gemini = [Response(gemini_response(decision(False)))]
    p.run()
    assert "2001" in p.state.inspect("1001")["progress"]
    p.clock.sleep(3601)
    p.http.gemini = [Response(gemini_response(decision()))]
    p.run()
    assert p.state.inspect("1001")["status"] == "alerted"
    assert p.http.count("generateContent") == 2
    assert not any("/1001/children" in url for _, url, _ in p.http.calls)


def test_carousel_unavailable_first_child_can_match_second(pipeline):
    p = pipeline
    p.http.posts = [post(media_type="CAROUSEL_ALBUM", children={"data": [
        {"id": "2001", "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/gone.jpg"},
        {"id": "2002", "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/two.jpg"}]})]
    p.http.images["https://scontent.cdninstagram.com/gone.jpg"] = Response(status=404)
    p.run()
    assert p.state.inspect("1001")["status"] == "alerted"
    assert p.http.count("generateContent") == 1


def test_incomplete_carousel_is_reviewed_not_rejected(pipeline):
    p = pipeline
    p.http.posts = [post(media_type="CAROUSEL_ALBUM", children={"data": [
        {"id": "2001", "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/one.jpg"}],
        "paging": {"next": "https://graph.facebook.com/ignored"}})]
    p.http.gemini = [Response(gemini_response(decision(False)))]
    p.run()
    assert p.state.inspect("1001")["status"] == "review"


def test_budget_backlog_survives_process_restart_and_source_disappearance(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, ai_run=1)
    p.http.posts = [post(str(x)) for x in (1001, 1002, 1003)]
    for row, color in zip(p.http.posts, ("orange", "blue", "green")):
        p.http.images[row["media_url"]] = Response(headers={"Content-Type": "image/jpeg"}, content=jpeg(color))
    p.run()
    assert p.http.count("generateContent") == 1
    p.state.close()
    p.state = State(p.cfg, p.http, clock=p.clock)
    p.http.posts = []
    for _ in range(2):
        p.clock.sleep(3601)
        p.run()
    assert p.http.count("generateContent") == 3
    assert p.state.stats()["queue"] == {"alerted": 3}


def test_daily_budget_exhaustion_retains_work_and_never_calls_ai(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, ai_day=0)
    p.run()
    assert p.http.count("generateContent") == 0
    # One bounded download computes the exact hash, allowing already-cached
    # assessments even after the AI budget has been exhausted.
    assert p.http.count("cdninstagram.com") == 1
    item = p.state.inspect("1001")
    assert item["status"] == "retry" and item["attempts"] == 0


def test_alert_budget_retains_positive_without_repeat_ai(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, alerts_day=0)
    p.run()
    assert p.state.inspect("1001")["result"]["match"]
    assert p.http.count("sendMessage") == 0
    p.cfg = replace(p.cfg, alerts_day=10)
    p.clock.sleep(86401)
    p.run()
    assert p.http.count("generateContent") == 1
    assert p.http.count("sendMessage") == 1


def test_telegram_429_retries_cached_positive(pipeline):
    p = pipeline
    p.http.telegram = [Response({"ok": False, "error_code": 429, "parameters": {"retry_after": 600}}, 429)]
    p.run()
    assert p.state.inspect("1001")["status"] == "retry"
    p.clock.sleep(601)
    p.http.telegram = []
    p.run()
    assert p.state.inspect("1001")["status"] == "alerted"
    assert p.http.count("generateContent") == 1


def test_telegram_timeout_enters_review_without_automatic_duplicate(pipeline):
    p = pipeline
    p.http.telegram = [requests.Timeout("https://api.telegram.org/bottelegram-secret/sendMessage")]
    p.run()
    item = p.state.inspect("1001")
    assert item["status"] == "review" and item["last_error"] == "telegram:delivery_unknown"
    p.clock.sleep(601)
    p.run()
    assert p.http.count("sendMessage") == 1


def test_crash_with_send_marker_needs_review(pipeline):
    p = pipeline
    p.run()
    p.state.db.execute("UPDATE tigerwatch_queue SET status='retry',data=?,result=?,next_attempt=0 WHERE id=?",
                       ('{"id":"1001"}', '{"match":true,"sending":true}', p.state.storage_id("1001")))
    p.run(discover=False)
    assert p.state.inspect("1001")["status"] == "review"
    assert p.http.count("sendMessage") == 1


def test_expired_cdn_refreshes_only_through_approved_source(pipeline):
    p = pipeline
    p.run()
    p.state.db.execute("DELETE FROM tigerwatch_queue")
    old = post(media_url="https://scontent.cdninstagram.com/old.jpg")
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": old}])
    p.http.images[old["media_url"]] = Response(status=403)
    p.run(discover=False)
    assert p.state.inspect("1001")["status"] == "alerted"
    assert p.worker.metrics["url_refreshes"] == 1
    assert all(not url.endswith("/1001") for _, url, _ in p.http.calls)


def test_inaccessible_post_retries_then_dead_letters(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, max_attempts=2)
    p.http.images[post()["media_url"]] = Response(status=404)
    p.run()
    assert p.state.inspect("1001")["attempts"] == 1
    before = len(p.http.calls)
    p.run()
    assert len(p.http.calls) - before == 1  # discovery only, no early retry
    p.clock.sleep(1000)
    p.run()
    assert p.state.inspect("1001")["status"] == "dead"
    assert p.http.count("generateContent") == 0


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_gemini_service_failures_preserve_queue_and_stop(pipeline, status):
    p = pipeline
    p.http.posts = [post("1001"), post("1002")]
    p.http.gemini = [Response({"error": "gemini-secret"}, status)]
    metrics = p.run()
    assert metrics["stopped"] == 1
    assert p.http.count("generateContent") == 1
    assert p.state.inspect("1001")["status"] == "retry"
    assert p.state.inspect("1002")["status"] == "pending"
    assert "gemini-secret" not in p.state.inspect("1001")["last_error"]


def test_invalid_gemini_json_has_backoff(pipeline):
    p = pipeline
    p.http.gemini = [Response(content=b"not json")]
    p.run()
    item = p.state.inspect("1001")
    assert item["status"] == "retry" and item["next_attempt"] > p.clock()
    p.run()
    assert p.http.count("generateContent") == 1


def test_video_never_uses_gemini(pipeline):
    p = pipeline
    p.http.posts = [post(media_type="VIDEO")]
    p.run()
    assert p.state.inspect("1001")["status"] == "unsupported"
    assert p.http.count("generateContent") == 0


def test_photo_delivery_requires_specific_permission(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, send_photo=True, photo_rights_confirmed=True, photo_media_ids=("1001",))
    p.run()
    assert p.http.count("sendPhoto") == 1
    assert p.http.sent[0]["files"]["photo"][2] == "image/jpeg"


def test_photo_flag_without_post_permission_sends_link(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, send_photo=True, photo_rights_confirmed=True, photo_media_ids=("9999",))
    p.run()
    assert p.http.count("sendPhoto") == 0 and p.http.count("sendMessage") == 1


def test_malicious_redirect_never_reaches_target_or_ai(pipeline):
    p = pipeline
    p.http.images[post()["media_url"]] = Response(status=302, headers={"Location": "https://127.0.0.1/secrets"})
    p.run()
    assert p.state.inspect("1001")["status"] == "dead"
    assert p.http.count("127.0.0.1") == 0 and p.http.count("generateContent") == 0
