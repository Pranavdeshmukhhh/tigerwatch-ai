import io
import json
import socket
from dataclasses import replace

import pytest
import requests
from PIL import Image

from tigerwatch.config import Config
from tigerwatch.errors import ProviderError, SetupError, UnsafeMedia
from tigerwatch.media import approved_cdn, download_image, normalize, permalink, public_dns
from tigerwatch.services import classify, telegram
from .fakes import FakeHTTP, Response, decision, gemini_response, jpeg


@pytest.mark.parametrize("url", ["http://scontent.cdninstagram.com/a", "https://cdninstagram.com.evil.test/a",
    "https://127.0.0.1/a", "https://user:pass@fbcdn.net/a", "https://fbcdn.net:8443/a",
    "https://fbcdn.net./a", "https://fbcdn.net\\@evil.test/a", "https://fbcdn.net/a#x", "https://fbcdn.net/a\n"])
def test_cdn_url_rejections(url):
    assert not approved_cdn(url)


@pytest.mark.parametrize("url", ["https://scontent.cdninstagram.com/a", "https://scontent.fna.fbcdn.net/a?sig=123"])
def test_cdn_url_allowed(url):
    assert approved_cdn(url)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"])
def test_dns_private_address_denied(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (ip, 443))])
    with pytest.raises(UnsafeMedia):
        public_dns("scontent.cdninstagram.com")


@pytest.mark.parametrize("headers,content", [
    ({"Content-Type": "image/svg+xml"}, b"<svg>"),
    ({"Content-Type": "image/jpeg"}, b"html"),
    ({"Content-Type": "image/png"}, jpeg()),
    ({"Content-Type": "image/jpeg", "Content-Length": "99999999"}, jpeg()),
    ({"Content-Type": "image/jpeg", "Content-Length": "broken"}, jpeg()),
    ({"Content-Type": "image/jpeg"}, b"x" * 8_000_001),
], ids=["svg", "invalid-jpeg", "mime-mismatch", "declared-oversize", "invalid-length", "stream-oversize"])
def test_image_validation(headers, content):
    http = FakeHTTP()
    url = "https://scontent.cdninstagram.com/test.jpg"
    response = Response(headers=headers, content=content)
    http.images[url] = response
    with pytest.raises(UnsafeMedia):
        download_image(http, url, resolve=lambda x: None)
    assert response.closed


def test_redirect_limit_and_close():
    http = FakeHTTP()
    url = "https://scontent.cdninstagram.com/loop"
    r = Response(status=302, headers={"Location": "/loop"})
    http.images[url] = r
    with pytest.raises(UnsafeMedia, match="redirect_limit"):
        download_image(http, url, resolve=lambda x: None)
    assert len(http.calls) == 4 and r.closed


def test_image_metadata_is_removed():
    im = Image.new("RGB", (25, 25), "orange")
    exif = Image.Exif()
    exif[270] = "sensitive-location"
    raw = io.BytesIO()
    im.save(raw, "JPEG", exif=exif)
    clean = normalize(raw.getvalue())
    with Image.open(io.BytesIO(clean)) as result:
        assert not result.getexif()
    assert b"sensitive-location" not in clean


@pytest.mark.parametrize("answer", [[], {"tiger": "true", "real_photo": True, "confidence": 0.9},
    decision(score=True), decision(score="0.9"), decision(score=float("nan")), decision(score=2),
    {**decision(), "location": "unwanted"}, {"tiger": True}])
def test_gemini_invalid_schema(answer):
    http = FakeHTTP()
    http.gemini = [Response(gemini_response(answer))]
    with pytest.raises(ProviderError, match="invalid_classification"):
        classify(http, replace(Config(), free_plans_confirmed=True), jpeg())


def test_gemini_truncated_or_blocked_response_is_retryable():
    http = FakeHTTP()
    http.gemini = [Response({"candidates": [{"finishReason": "MAX_TOKENS"}]})]
    with pytest.raises(ProviderError, match="invalid_classification"):
        classify(http, replace(Config(), free_plans_confirmed=True), jpeg())


def test_telegram_rejects_ok_without_message_id():
    http = FakeHTTP()
    http.telegram = [Response({"ok": True})]
    with pytest.raises(ProviderError) as got:
        telegram(http, "test")
    assert got.value.unknown


def test_telegram_transport_never_leaks_token():
    http = FakeHTTP()
    http.telegram = [requests.Timeout("bottelegram-secret/sendMessage")]
    with pytest.raises(ProviderError) as got:
        telegram(http, "test")
    assert got.value.unknown and "telegram-secret" not in str(got.value)


@pytest.mark.parametrize("env", [{"HASHTAGS": ",".join("tag" + str(x) for x in range(31))},
    {"TIGER_CONFIDENCE": "NaN"}, {"SEND_PHOTO": "true"}, {"SEND_PHOTO": "maybe"},
    {"GEMINI_MODEL": "../../bad"}, {"ACCOUNTS": "bad){id}"},
    {"PHOTO_RESHARE_SOURCES": "#tiger", "HASHTAGS": "tiger"}])
def test_invalid_configuration_fails_early(env):
    with pytest.raises(SetupError):
        Config.from_env(env)


def test_instagram_permalink_rejects_credentials_ports_and_tracking():
    assert permalink("https://u:p@instagram.com/p/abc/") is None
    assert permalink("https://instagram.com:444/p/abc/") is None
    assert permalink("https://instagram.com/p/abc/?gps=1") == "https://www.instagram.com/p/abc/"


def test_normalized_jpeg_is_valid():
    raw = normalize(jpeg())
    with Image.open(io.BytesIO(raw)) as im:
        assert im.format == "JPEG" and max(im.size) <= 900


def test_model_payload_uses_json_schema_and_bounded_output():
    http = FakeHTTP()
    classify(http, replace(Config(), free_plans_confirmed=True), jpeg())
    cfg = http.ai_payloads[0]["generationConfig"]
    assert cfg["responseJsonSchema"]["additionalProperties"] is False
    assert cfg["maxOutputTokens"] == 1536
    assert json.loads(json.dumps(cfg)) == cfg
