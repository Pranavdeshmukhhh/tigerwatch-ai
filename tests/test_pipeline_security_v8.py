"""Pipeline regression checks use synthetic bytes and mocked providers only."""
import json
from dataclasses import replace

import pytest

from tigerwatch.errors import ExpiredMedia, ProviderError, StoreError
from tigerwatch.net import JSON_LIMIT, json_request, strict_json_loads
from tigerwatch.services import classify, telegram
from .fakes import Response, decision, gemini_response, jpeg, post


@pytest.mark.parametrize("raw", [
    '{"ok":false,"ok":true}',
    '{"result":{"id":1,"id":2}}',
    '{"score":NaN}', '{"score":Infinity}', '{"score":-Infinity}', '{"score":1e9999}',
])
def test_provider_json_rejects_ambiguous_or_nonfinite_values(raw):
    with pytest.raises(ValueError):
        strict_json_loads(raw)


def test_provider_json_accepts_normal_bounded_data():
    assert strict_json_loads(b'{"ok":true,"result":{"id":123},"score":0.9}') == {
        "ok": True, "result": {"id": 123}, "score": .9}


def test_ambiguous_telegram_success_is_unknown_delivery(pipeline):
    p = pipeline
    p.http.telegram = [Response(content=b'{"ok":false,"ok":true,"result":{"message_id":77}}')]
    with pytest.raises(ProviderError) as got:
        telegram(p.http, "synthetic diagnostic")
    assert got.value.unknown and got.value.provider == "telegram"


@pytest.mark.parametrize("headers,content", [
    ({"Content-Length": str(JSON_LIMIT + 1)}, b'{}'),
    ({"Content-Length": "invalid"}, b'{}'),
    ({}, b'x' * (JSON_LIMIT + 1)),
])
def test_unreadable_telegram_response_keeps_delivery_uncertain(pipeline, headers, content):
    p = pipeline
    p.http.telegram = [Response(headers=headers, content=content)]
    with pytest.raises(ProviderError) as got:
        telegram(p.http, "synthetic diagnostic")
    assert got.value.unknown and got.value.stop and got.value.provider == "telegram"


def test_unreadable_delivery_is_reviewed_and_never_reclassified_or_resent(pipeline):
    p = pipeline
    p.http.telegram = [Response(headers={"Content-Length": str(JSON_LIMIT + 1)}, content=b'{}')]
    p.run()
    item = p.state.inspect("1001")
    assert item["status"] == "review" and item["last_error"] == "telegram:delivery_unknown"
    assert item["result"]["sending"] is True
    p.run()
    assert p.http.count("generateContent") == p.http.count("sendMessage") == 1


def test_ambiguous_model_json_cannot_become_a_positive(pipeline):
    p = pipeline
    answer = json.dumps(decision()).replace('"real_photo": true', '"real_photo": false, "real_photo": true')
    body = gemini_response(decision())
    body["candidates"][0]["content"]["parts"][0]["text"] = answer
    p.http.gemini = [Response(body)]
    with pytest.raises(ProviderError, match="invalid_classification"):
        classify(p.http, p.cfg, jpeg())


def test_nontelegram_response_limit_is_provider_scoped_without_delivery_flag(pipeline):
    p = pipeline
    p.http.gemini = [Response(headers={"Content-Length": str(JSON_LIMIT + 1)}, content=b'{}')]
    with pytest.raises(ProviderError) as got:
        json_request(p.http, "POST", "https://generativelanguage.googleapis.com/test", "gemini", json={})
    assert got.value.provider == "gemini" and not got.value.unknown


@pytest.mark.parametrize("sending", [False, True])
def test_safety_block_precedes_an_older_positive_or_uncertain_delivery(pipeline, sending):
    p = pipeline
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": {**post(), "media_blocked": True}}])
    item = p.state.claim()
    p.state.save(item, release=True, status="retry", result={"match": True, "confidence": .99,
        "child_id": "1001", "sending": sending, "source_link": post()["permalink"]})
    p.run(discover=False)
    retained = p.state.inspect("1001")
    assert retained["status"] == "review" and retained["last_error"] == "media_safety_block"
    assert retained["result"]["media_not_processed"]
    assert not retained["result"].get("match") and not p.http.calls
    if sending:
        assert retained["result"]["delivery_unknown"] is True


def test_safety_block_after_permalink_refresh_never_forwards_old_positive(pipeline):
    p = pipeline
    p.http.posts[0]["caption"] = "suspected child abuse reference"
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": {"id": "1001", "media_type": "IMAGE"}}])
    item = p.state.claim()
    p.state.save(item, release=True, status="retry", result={"match": True, "confidence": .99, "child_id": "1001"})
    p.run(discover=False)
    assert p.state.inspect("1001")["last_error"] == "media_safety_block"
    assert p.http.count("cdninstagram.com") == p.http.count("generateContent") == p.http.count("api.telegram.org") == 0


def test_safety_block_during_photo_url_refresh_never_falls_back_to_alert(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, send_photo=True, photo_rights_confirmed=True, photo_sources=("#tiger",))
    p.http.posts[0]["caption"] = "suspected child abuse reference"
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": post()}])
    item = p.state.claim()
    p.state.save(item, release=True, status="retry", result={"match": True, "confidence": .99, "child_id": "1001"})
    p.http.images[post()["media_url"]] = ExpiredMedia()
    p.run(discover=False)
    assert p.state.inspect("1001")["last_error"] == "media_safety_block"
    assert p.http.count("generateContent") == p.http.count("api.telegram.org") == 0


def test_current_scope_does_not_accept_a_malformed_prefixed_id(pipeline):
    state = pipeline.state
    for tail in ("", "../private", "other:1001", "1" * 51):
        with pytest.raises(StoreError, match="invalid_media_id_or_target_scope"):
            state.storage_id(state.cfg.scope + ":" + tail)


def test_queue_response_cannot_expose_another_scope(pipeline):
    state = pipeline.state
    with pytest.raises(StoreError, match="scope_or_id"):
        state.logical_row({"id": "f" * 24 + ":1001", "data": {"private": "other watch"}})
    assert state.logical_row({"id": state.cfg.scope + ":1001"}) == {"id": "1001"}
    assert state.logical_row({"id": "1001"}) == {"id": "1001"}
