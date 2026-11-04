import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
import requests

from tigerwatch.errors import LeaseLost, StoreError
from tigerwatch.net import Redact
from tigerwatch.store import State
from .fakes import Response, post


def enqueue(state, ident="1001", source="#tiger"):
    state.enqueue([{"id": ident, "source": source, "data": post(ident)}])


def test_sqlite_concurrent_claim_has_one_winner(pipeline):
    p = pipeline
    enqueue(p.state)
    def claim(_):
        s = State(p.cfg, p.http, clock=p.clock)
        try:
            return s.claim()
        finally:
            s.close()
    with ThreadPoolExecutor(8) as pool:
        values = list(pool.map(claim, range(8)))
    assert sum(x is not None for x in values) == 1


def test_sqlite_concurrent_daily_reservations_never_exceed_cap(pipeline):
    p = pipeline
    def reserve(_):
        s = State(p.cfg, p.http, clock=p.clock)
        try:
            return s.reserve("ai", 5, 0)["ok"]
        finally:
            s.close()
    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(reserve, range(24))) == 5
    assert p.state.stats()["today"]["ai"] == 5


def test_stale_worker_cannot_save_after_new_claim(pipeline):
    p = pipeline
    enqueue(p.state)
    old = p.state.claim()
    p.clock.sleep(p.cfg.lease_seconds + 1)
    new = p.state.claim()
    assert new["lease_token"] != old["lease_token"]
    with pytest.raises(LeaseLost):
        p.state.save(old, result={"match": True})
    p.state.save(new, release=True, status="retry", next_attempt=p.clock() + 10)


def test_rediscovery_does_not_overwrite_leased_item_or_retry_schedule(pipeline):
    p = pipeline
    enqueue(p.state)
    item = p.state.claim()
    p.state.save(item, progress={"child": {"tiger": False}})
    changed = post(media_url="https://scontent.cdninstagram.com/new.jpg")
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": changed}])
    assert p.state.inspect("1001")["data"]["media_url"] != changed["media_url"]
    p.state.save(item, release=True, status="retry", next_attempt=p.clock() + 100, attempts=2)
    p.state.enqueue([{"id": "1001", "source": "#tiger", "data": changed}])
    row = p.state.inspect("1001")
    assert row["attempts"] == 2 and row["next_attempt"] == p.clock() + 100
    assert row["progress"] == {"child": {"tiger": False}}


def test_queue_expiry_dead_letters_instead_of_silently_deleting(pipeline):
    p = pipeline
    enqueue(p.state)
    p.clock.sleep(p.cfg.queue_hours * 3600 + 1)
    p.state.maintain()
    item = p.state.inspect("1001")
    assert item["status"] == "dead" and item["last_error"] == "queue_expired"
    assert item["data"] == {}


def test_dead_letter_dedup_expiry(pipeline):
    p = pipeline
    enqueue(p.state)
    item = p.state.claim()
    p.state.save(item, release=True, status="dead", data={})
    p.clock.sleep(p.cfg.dedup_days * 86400 + 1)
    p.state.maintain()
    assert p.state.inspect("1001") is None


def test_hashtag_window_cannot_be_bypassed_by_config_rotation_or_cached_ids(pipeline):
    p = pipeline
    for n in range(30):
        assert p.state.admit_tag("123", f"tag{n}")
    assert not p.state.admit_tag("123", "newtag")
    p.clock.sleep(600000)
    assert p.state.admit_tag("123", "tag0")
    p.clock.sleep(4801)
    assert p.state.admit_tag("123", "newtag")
    assert p.state.admit_tag("different-account", "extra")


def test_legacy_sqlite_migrates_queue_seen_and_daily_usage_once(tmp_path, pipeline):
    path = str(tmp_path / "legacy.sqlite3")
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE tigerwatch_seen(id TEXT PRIMARY KEY,status TEXT,source TEXT);
        CREATE TABLE tigerwatch_pending(id TEXT PRIMARY KEY,source TEXT,data TEXT,first_seen TEXT);
        CREATE TABLE tigerwatch_daily_usage(day TEXT PRIMARY KEY,used INTEGER);
        INSERT INTO tigerwatch_seen VALUES('1','alerted','#tiger');
        INSERT INTO tigerwatch_daily_usage VALUES('2026-10-25',7);
        """)
        db.execute("INSERT INTO tigerwatch_pending VALUES(?,?,?,?)", ("2", "#tiger", json.dumps(post("2")), "2026-10-25T00:00:00+00:00"))
    cfg = replace(pipeline.cfg, sqlite_path=path)
    for _ in range(2):
        s = State(cfg, pipeline.http, clock=pipeline.clock)
        assert s.inspect("1")["status"] == "alerted"
        assert s.inspect("2")["status"] == "pending"
        assert s.db.execute("SELECT used FROM tigerwatch_counters WHERE day='2026-10-25'").fetchone()[0] == 7
        s.close()


def test_unknown_delivery_manual_retry_requires_acknowledgement(pipeline):
    p = pipeline
    enqueue(p.state)
    item = p.state.claim()
    p.state.save(item, release=True, status="review", last_error="telegram:delivery_unknown", result={"match": True, "sending": True})
    with pytest.raises(StoreError, match="acknowledge"):
        p.state.call("retry", id="1001", acknowledge=False)
    assert p.state.call("retry", id="1001", acknowledge=True)
    assert p.state.inspect("1001")["result"]["sending"] is False


def test_supabase_rpc_contract_and_mocked_pipeline(pipeline, monkeypatch):
    p = pipeline
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "server-secret")
    local = p.state
    class Bridge:
        def request(self, method, url, **kwargs):
            if url.startswith("https://example.supabase.co"):
                assert method == "POST" and kwargs["allow_redirects"] is False
                assert kwargs["headers"]["Authorization"] == "Bearer server-secret"
                body = kwargs["json"]
                assert set(body) == {"op", "payload"}
                return Response(local.call(body["op"], **body["payload"]))
            return p.http.request(method, url, **kwargs)
    cfg = replace(p.cfg, supabase_url="https://example.supabase.co")
    remote = State(cfg, Bridge(), clock=p.clock)
    remote.enqueue([{"id": "1001", "source": "#tiger", "data": post()}])
    item = remote.claim()
    assert item["status"] == "processing"
    remote.save(item, release=True, status="retry", next_attempt=0)
    assert remote.reserve("ai", 2, 0)["ok"]
    assert remote.stats()["today"]["ai"] == 1
    # Exercise the full worker over mocked Supabase HTTP transport and provider HTTP.
    from tigerwatch.meta import Meta
    from tigerwatch.media import download_image
    from tigerwatch.worker import Worker
    bridge = Bridge()
    Worker(cfg, remote, Meta(cfg, bridge, remote, clock=p.clock, sleep=p.clock.sleep), bridge,
           clock=p.clock, sleep=p.clock.sleep, downloader=lambda h, u: download_image(h, u, resolve=lambda x: None)).run()
    assert remote.inspect("1001")["status"] == "alerted"


def test_database_transport_failure_is_redacted_and_not_retried(pipeline, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "server-secret")
    class Broken:
        calls = 0
        def request(self, *args, **kwargs):
            self.calls += 1
            raise requests.Timeout("server-secret https://project.supabase.co")
    http = Broken()
    store = State(replace(pipeline.cfg, supabase_url="https://project.supabase.co"), http)
    with pytest.raises(StoreError) as got:
        store.reserve("ai", 20, 0)
    assert "server-secret" not in str(got.value) and http.calls == 1


def test_log_redaction_covers_secrets_queries_and_bot_paths():
    r = logging.LogRecord("test", logging.ERROR, "", 0,
                          "server-secret access_token=unknown /botunknown/sendMessage", (), None)
    Redact(["server-secret"]).filter(r)
    assert "server-secret" not in r.msg and "unknown" not in r.msg
