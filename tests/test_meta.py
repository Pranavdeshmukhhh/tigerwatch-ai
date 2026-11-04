from dataclasses import replace

import pytest
import requests

from tigerwatch.errors import ProviderError
from tigerwatch.meta import FIELDS, Meta, clean_post, cursor, timestamp
from .fakes import Response, post


def client(p):
    return Meta(p.cfg, p.http, p.state, clock=p.clock, sleep=p.clock.sleep)


def test_hashtag_repeated_cursor_can_continue(pipeline):
    p = pipeline
    p.http.hashtag_pages = [
        {"data": [post("1001")], "paging": {"cursors": {"after": "SAME"}}},
        {"data": [post("1002")], "paging": {"cursors": {"after": "SAME"}}},
        {"data": [post("1003")]}]
    rows = client(p).hashtag_media("tiger")
    assert [x["id"] for x in rows] == ["1001", "1002", "1003"]
    assert len(p.state.stats()["queue"]) == 1
    assert p.state.stats()["queue"]["pending"] == 3


def test_hashtag_repeated_content_stops(pipeline):
    p = pipeline
    p.http.hashtag_pages = [{"data": [post()], "paging": {"cursors": {"after": "SAME"}}}]
    assert len(client(p).hashtag_media("tiger")) == 1
    assert p.http.count("/recent_media") == 2


def test_business_pagination_without_next_url(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, accounts=("sanctuary",))
    p.http.business_pages = [{"data": [post("1001")], "paging": {"cursors": {"after": "PAGE2=="}}},
                             {"data": [post("1002")]}]
    assert len(client(p).business_media("sanctuary")) == 2
    calls = [k["params"]["fields"] for _, _, k in p.http.calls]
    assert ".after(PAGE2==)" in calls[1]
    assert "children.limit(50)" in calls[0]


def test_page_caps_bound_requests(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, pages=2)
    p.http.hashtag_pages = [{"data": [post(str(1000 + x))], "paging": {"cursors": {"after": "SAME"}}} for x in range(5)]
    assert len(client(p).hashtag_media("tiger")) == 2
    assert p.http.count("/recent_media") == 2


def test_meta_auth_header_never_token_query(pipeline):
    p = pipeline
    client(p).hashtag_media("tiger")
    for _, url, kwargs in p.http.calls:
        assert "meta-secret" not in url
        assert "access_token" not in kwargs["params"]
        assert kwargs["headers"]["Authorization"] == "Bearer meta-secret"
    assert "caption" not in FIELDS


def test_meta_authentication_error_is_redacted(pipeline):
    p = pipeline
    p.http.meta_failure = Response({"error": {"code": 190, "message": "meta-secret leaked"}}, 400)
    with pytest.raises(ProviderError) as got:
        client(p).get("123", fields="id")
    assert got.value.stop and not got.value.retry
    assert "meta-secret" not in str(got.value)


def test_meta_network_exception_is_redacted_and_bounded(pipeline):
    p = pipeline
    p.http.meta_failure = requests.Timeout("access_token=meta-secret")
    with pytest.raises(ProviderError) as got:
        client(p).get("123")
    assert "meta-secret" not in str(got.value)
    assert len(p.http.calls) == 3


def test_meta_get_5xx_retries_then_recovers(pipeline):
    p = pipeline
    p.http.meta_failure = [Response({}, 503), None]
    assert client(p).get("123")["id"] == "123"
    assert len(p.http.calls) == 2


def test_meta_429_honors_retry_after_without_loop(pipeline):
    p = pipeline
    p.http.meta_failure = Response({"error": {"code": 4}}, 429, {"Retry-After": "1800"})
    with pytest.raises(ProviderError) as got:
        client(p).get("123")
    assert got.value.wait == 1800 and len(p.http.calls) == 1


def test_first_page_is_committed_before_later_page_outage(pipeline):
    p = pipeline
    meta = client(p)
    def get(path, **kwargs):
        if path == "ig_hashtag_search":
            return {"data": [{"id": "555"}]}
        if kwargs.get("after"):
            raise ProviderError("meta", "temporary_failure", stop=True)
        return {"data": [post()], "paging": {"cursors": {"after": "NEXT"}}}
    meta.get = get
    with pytest.raises(ProviderError):
        meta.hashtag_media("tiger")
    assert p.state.inspect("1001")["status"] == "pending"


@pytest.mark.parametrize("bad", ["abc){id}", "\n", "a.b", {}, ["cursor"], "x" * 3000])
def test_invalid_paging_cursor_rejected(bad):
    with pytest.raises(ProviderError):
        cursor({"paging": {"cursors": {"after": bad}}})


@pytest.mark.parametrize("value", [1792886400, "1792886400", "2026-10-25T00:00:00Z", "2026-10-25T00:00:00+00:00"])
def test_timestamp_formats(value):
    assert timestamp(value) is not None


def test_untrusted_rows_are_minimized_and_links_cleaned(pipeline):
    p = pipeline
    raw = post(caption="sensitive coords", location={"latitude": 1}, owner="private", permalink="https://instagram.com/p/abc/?igsh=tracking")
    data = clean_post(raw, p.cfg, p.clock())
    assert not {"caption", "location", "owner"} & data.keys()
    assert data["permalink"] == "https://www.instagram.com/p/abc/"
    assert clean_post(post(id={"evil": 1}), p.cfg, p.clock()) is None


def test_usage_header_stops_next_request(pipeline):
    p = pipeline
    p.http.meta_failure = [Response({"id": "123"}, headers={"x-app-usage": '{"call_count":95}'})]
    meta = client(p)
    meta.get("123")
    with pytest.raises(ProviderError, match="cooldown"):
        meta.get("123")
    assert len(p.http.calls) == 1


def test_meta_request_cap(pipeline):
    p = pipeline
    p.cfg = replace(p.cfg, max_meta_calls=1)
    meta = client(p)
    meta.get("123")
    with pytest.raises(ProviderError, match="request_cap"):
        meta.get("123")
