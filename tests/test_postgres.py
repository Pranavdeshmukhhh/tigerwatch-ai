"""Optional real PostgreSQL tests; no live Supabase/provider traffic.

TEST_POSTGRES_DSN must point at a disposable, local database with an admin role.
The fixture truncates TigerWatch tables and tests v3 import in a temporary DB.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
Jsonb = psycopg.types.json.Jsonb

DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_POSTGRES_DSN not set; local PostgreSQL tests optional")
SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"


def rpc(op, **payload):
    from tigerwatch.targets import LEGACY_SCOPE
    scope = payload.setdefault("scope", LEGACY_SCOPE)
    if op in ("save", "inspect", "retry", "feedback") and ":" not in payload["id"]:
        payload["id"] = scope + ":" + payload["id"]
    if op == "enqueue":
        payload["items"] = [{**x, "id": x["id"] if ":" in x["id"] else scope + ":" + x["id"]} for x in payload["items"]]
    with psycopg.connect(DSN) as c:
        c.execute("SET LOCAL ROLE service_role")
        value = c.execute("SELECT public.tigerwatch_state(%s,%s)", (op, Jsonb(payload))).fetchone()[0]
        if op in ("claim", "inspect") and value:
            value["id"] = value["id"].split(":", 1)[-1]
        return value


@pytest.fixture(autouse=True)
def database():
    with psycopg.connect(DSN, autocommit=True) as c:
        for role, options in (("anon", ""), ("authenticated", ""), ("service_role", "BYPASSRLS")):
            if not c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                c.execute(f"CREATE ROLE {role} {options}")
        c.execute(SCHEMA.read_text())
        c.execute("TRUNCATE public.tigerwatch_queue,public.tigerwatch_counters,public.tigerwatch_kv,public.tigerwatch_hashtag_windows,public.tigerwatch_source_claims,public.tigerwatch_feedback,public.tigerwatch_image_cache")


def enqueue(ident="1001"):
    return rpc("enqueue", items=[{"id": ident, "source": "#tiger", "data": {"id": ident}}])


def test_postgres_migration_is_idempotent():
    enqueue()
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(SCHEMA.read_text())
        c.execute(SCHEMA.read_text())
    assert rpc("inspect", id="1001")["status"] == "pending"


def test_postgres_concurrent_claims_and_fencing():
    enqueue()
    with ThreadPoolExecutor(8) as pool:
        rows = list(pool.map(lambda _: rpc("claim", token=uuid4().hex, lease=600), range(16)))
    winner = next(x for x in rows if x)
    assert sum(x is not None for x in rows) == 1
    assert not rpc("save", id="1001", token="wrong", lease=600, release=True, patch={"status": "alerted"})
    assert rpc("save", id="1001", token=winner["lease_token"], lease=600, release=True, patch={"status": "retry"})


def test_postgres_concurrent_budget_is_atomic():
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: rpc("reserve", resource="ai", limit=7, interval=0)["ok"], range(32)))
    assert sum(results) == 7
    assert rpc("stats")["today"]["ai"] == 7


def test_postgres_budget_pacing():
    assert rpc("reserve", resource="alerts", limit=10, interval=30)["ok"]
    result = rpc("reserve", resource="alerts", limit=10, interval=30)
    assert not result["ok"] and result["reason"] == "pace" and result["wait"] > 0


def test_postgres_30_hashtag_windows():
    for i in range(30):
        assert rpc("tag", account="123", tag=f"tag{i}")
    assert not rpc("tag", account="123", tag="extra")
    assert rpc("tag", account="123", tag="tag0")


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_postgres_rls_and_rpc_permissions(role):
    enqueue()
    with psycopg.connect(DSN) as c:
        c.execute(f"SET LOCAL ROLE {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT public.tigerwatch_state('stats','{}')")
    with psycopg.connect(DSN) as c:
        c.execute(f"SET LOCAL ROLE {role}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM public.tigerwatch_queue")


def test_postgres_legacy_import():
    dbname = "tw_legacy_" + uuid4().hex
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {dbname}")
    try:
        with psycopg.connect(DSN, dbname=dbname, autocommit=True) as c:
            c.execute("""
            CREATE TABLE public.tigerwatch_seen(id TEXT PRIMARY KEY,status TEXT,source TEXT,checked_at timestamptz default now());
            CREATE TABLE public.tigerwatch_pending(id TEXT PRIMARY KEY,source TEXT,data jsonb,first_seen timestamptz default now());
            CREATE TABLE public.tigerwatch_daily_usage(day date primary key,used integer);
            INSERT INTO public.tigerwatch_seen(id,status,source) VALUES('1','alerted','#tiger');
            INSERT INTO public.tigerwatch_pending(id,source,data) VALUES('2','#tiger','{"id":"2"}');
            INSERT INTO public.tigerwatch_daily_usage VALUES(current_date,9);
            """)
            c.execute(SCHEMA.read_text())
            c.execute(SCHEMA.read_text())
            assert c.execute("SELECT status FROM public.tigerwatch_queue WHERE id='legacy-tiger-v4:1'").fetchone()[0] == "alerted"
            assert c.execute("SELECT status FROM public.tigerwatch_queue WHERE id='legacy-tiger-v4:2'").fetchone()[0] == "pending"
            assert c.execute("SELECT used FROM public.tigerwatch_counters WHERE resource='ai'").fetchone()[0] == 9
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE {dbname}")


def test_postgres_supabase_rpc_transport_to_real_database(pipeline, monkeypatch):
    from dataclasses import replace
    from tigerwatch.store import State
    from .fakes import Response
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
    class HTTP:
        def request(self, method, url, **kwargs):
            assert url.endswith("/rest/v1/rpc/tigerwatch_state")
            body = kwargs["json"]
            return Response(rpc(body["op"], **body["payload"]))
    store = State(replace(pipeline.cfg, supabase_url="https://test.supabase.co"), HTTP())
    store.enqueue([{"id": "1001", "source": "#tiger", "data": {"id": "1001"}}])
    item = store.claim()
    store.save(item, release=True, status="alerted", data={})
    assert store.inspect("1001")["status"] == "alerted"


def test_postgres_expired_queue_is_dead_lettered():
    enqueue()
    with psycopg.connect(DSN) as c:
        c.execute("UPDATE public.tigerwatch_queue SET first_seen=0")
    assert rpc("maintain", hours=72, days=90)
    assert rpc("inspect", id="1001")["last_error"] == "queue_expired"


def test_postgres_complete_pipeline_with_mocked_providers(pipeline, monkeypatch):
    from dataclasses import replace
    from tigerwatch.media import download_image
    from tigerwatch.meta import Meta
    from tigerwatch.store import State
    from tigerwatch.worker import Worker
    from .fakes import Response
    p = pipeline
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
    class HTTP:
        def request(self, method, url, **kwargs):
            if url.startswith("https://test.supabase.co"):
                body = kwargs["json"]
                return Response(rpc(body["op"], **body["payload"]))
            return p.http.request(method, url, **kwargs)
    cfg = replace(p.cfg, supabase_url="https://test.supabase.co")
    http = HTTP()
    state = State(cfg, http)
    for _ in range(2):
        Worker(cfg, state, Meta(cfg, http, state), http,
               downloader=lambda h, u: download_image(h, u, resolve=lambda x: None)).run()
    assert state.stats()["queue"] == {"alerted": 1}
    assert p.http.count("generateContent") == 1 and p.http.count("sendMessage") == 1


def test_postgres_target_namespaces_isolate_claims_but_share_budget():
    scope1, scope2 = "a" * 24, "b" * 24
    for scope in (scope1, scope2):
        rpc("enqueue", scope=scope, items=[{"id": "1001", "source": "#demo", "data": {"id": "1001"}}])
    first = rpc("claim", scope=scope1, token="first", lease=600)
    second = rpc("claim", scope=scope2, token="second", lease=600)
    assert first["id"] == second["id"] == "1001"
    assert rpc("claim", scope=scope1, token="third", lease=600) is None
    assert rpc("reserve", scope=scope1, resource="ai", limit=1, interval=0)["ok"]
    assert not rpc("reserve", scope=scope2, resource="ai", limit=1, interval=0)["ok"]


def test_postgres_rediscovery_preserves_hydrated_retry_and_progress():
    link = "https://www.instagram.com/p/fixture/"
    hydrated = {"id": "1001", "permalink": link, "media_type": "IMAGE", "needs_hydration": False,
                "media_url": "https://scontent.cdninstagram.com/photo.jpg"}
    rpc("enqueue", items=[{"id": "1001", "source": "@fixture", "data": hydrated}])
    item = rpc("claim", token="fixture", lease=600)
    assert rpc("save", id="1001", token=item["lease_token"], lease=600, release=True,
               patch={"status": "retry", "progress": {"1001": {"match": False}}})
    stub = {"id": "1001", "permalink": link, "needs_hydration": True}
    rpc("enqueue", items=[{"id": "1001", "source": "@fixture", "data": stub}])
    retained = rpc("inspect", id="1001")
    assert retained["data"] == hydrated
    assert retained["progress"] == {"1001": {"match": False}}


def test_postgres_review_lists_are_scope_isolated():
    scope1, scope2 = "a" * 24, "b" * 24
    for scope in (scope1, scope2):
        rpc("enqueue", scope=scope, items=[{"id": "1001", "source": "@fixture", "data": {"id": "1001"}}])
        item = rpc("claim", scope=scope, token="fixture", lease=600)
        rpc("save", scope=scope, id="1001", token=item["lease_token"], lease=600, release=True,
            patch={"status": "review", "result": {"source_link": "https://www.instagram.com/p/fixture/"}})
    assert len(rpc("review_list", scope=scope1)) == 1
    assert rpc("review_list", scope=scope1)[0]["id"] == scope1 + ":1001"
