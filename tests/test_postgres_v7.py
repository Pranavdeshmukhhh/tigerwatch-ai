"""Additional real local PostgreSQL v7 operations; disposable database only."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from .test_postgres import DSN, database as database, psycopg, rpc

pytestmark = pytest.mark.skipif(not DSN, reason="TEST_POSTGRES_DSN not set; local PostgreSQL tests optional")
KEY="a"*64
DECISION={"match": False, "confidence": 0.1}


def test_pg_cache_concurrent_claim_and_commit_fencing():
    def claim(_):
        token=uuid4().hex
        return token,rpc("cache_claim",key=KEY,token=token,lease=120)
    with ThreadPoolExecutor(8) as pool:
        results=list(pool.map(claim,range(16)))
    owners=[token for token,value in results if value["status"] == "claimed"]
    assert len(owners) == 1
    assert sum(value["status"]=="busy" for _,value in results) == 15
    assert not rpc("cache_commit",key=KEY,token="stale",decision=DECISION)
    assert not rpc("cache_invalidate",key=KEY)
    assert rpc("cache_commit",key=KEY,token=owners[0],decision=DECISION)
    assert rpc("cache_claim",key=KEY,token="next",lease=120) == {"status":"hit","value":DECISION}
    assert rpc("cache_get",key=KEY) == DECISION
    assert rpc("cache_invalidate",key=KEY)
    assert rpc("cache_get",key=KEY) is None


def test_pg_cache_scope_expiry_and_release():
    assert rpc("cache_put",key=KEY,decision=DECISION)
    assert rpc("cache_get",scope="b"*24,key=KEY) is None
    with psycopg.connect(DSN) as c:
        c.execute("UPDATE public.tigerwatch_image_cache SET expires_at=0")
    assert rpc("cache_get",key=KEY) is None
    assert rpc("cache_claim",key=KEY,token="owner",lease=120)["status"] == "claimed"
    with psycopg.connect(DSN) as c:
        c.execute("UPDATE public.tigerwatch_image_cache SET leased_until=0")
    assert not rpc("cache_commit",key=KEY,token="owner",decision=DECISION)
    assert rpc("cache_claim",key=KEY,token="new",lease=120)["status"] == "claimed"
    assert not rpc("cache_release",key=KEY,token="owner")
    assert rpc("cache_release",key=KEY,token="new")


def test_pg_feedback_changes_only_label_and_dashboard_scope():
    scope="a"*24
    rpc("enqueue",scope=scope,items=[{"id":"1001","source":"@test","data":{"id":"1001"}}])
    assert not rpc("feedback",scope=scope,id="1001",verdict="correct")
    item=rpc("claim",scope=scope,token="owner",lease=600)
    assert rpc("save",scope=scope,id="1001",token=item["lease_token"],lease=600,release=True,
               patch={"status":"review","result":{"source_link":"https://www.instagram.com/p/Test/"}})
    before=rpc("inspect",scope=scope,id="1001")
    assert rpc("feedback",scope=scope,id="1001",verdict="incorrect")
    assert rpc("inspect",scope=scope,id="1001") == before
    assert rpc("review_list",scope=scope)[0]["feedback"] == "incorrect"
    assert rpc("dashboard",scope=scope)["feedback"] == {"incorrect":1}
    assert rpc("dashboard",scope="b"*24)["feedback"] == {}
    assert rpc("claim",scope=scope,token="other",lease=600) is None


def test_pg_newest_first_and_source_fairness():
    for ident,source in (("1","@one"),("2","@one"),("3","@two")):
        rpc("enqueue",items=[{"id":ident,"source":source,"data":{"id":ident}}])
    with psycopg.connect(DSN) as c:
        c.execute("UPDATE public.tigerwatch_queue SET first_seen=100 WHERE id LIKE '%%:1'")
        c.execute("UPDATE public.tigerwatch_queue SET first_seen=200 WHERE id LIKE '%%:2'")
        c.execute("UPDATE public.tigerwatch_queue SET first_seen=300 WHERE id LIKE '%%:3'")
    assert rpc("claim",token="first",lease=600)["id"] == "3"
    assert rpc("claim",token="second",lease=600)["id"] == "2"
    view=rpc("dashboard")
    assert view["backlog"]["pending"] == 3 and view["backlog"]["due"] == 1
    assert view["backlog"]["oldest_first_seen"] == 100


@pytest.mark.parametrize("role",["anon","authenticated"])
def test_pg_new_table_privileges_are_server_only(role):
    for table in ("tigerwatch_feedback","tigerwatch_image_cache"):
        with psycopg.connect(DSN) as c:
            c.execute(f"SET LOCAL ROLE {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM public."+table)


def test_pg_cache_capacity_preserves_active_claim():
    from tigerwatch.targets import LEGACY_SCOPE
    with psycopg.connect(DSN) as c:
        c.execute("""INSERT INTO public.tigerwatch_image_cache(scope,key,decision,expires_at,lease_token,leased_until,updated_at)
          SELECT %s,lpad(to_hex(g),64,'0'),CASE WHEN g=0 THEN NULL ELSE '{}'::jsonb END,
            CASE WHEN g=0 THEN 0 ELSE extract(epoch from now())+604800 END,
            CASE WHEN g=0 THEN 'active' ELSE NULL END,
            CASE WHEN g=0 THEN extract(epoch from now())+120 ELSE 0 END,g
          FROM generate_series(0,4999) g""",(LEGACY_SCOPE,))
    assert rpc("cache_put",key="f"*64,decision=DECISION)
    assert rpc("cache_claim",key="0"*64,token="other",lease=120)["status"] == "busy"
    assert rpc("cache_get",key=format(1,"064x")) is None
    with psycopg.connect(DSN) as c:
        assert c.execute("SELECT count(*) FROM public.tigerwatch_image_cache").fetchone()[0] == 5000


def test_pg_v6_counter_constraint_migrates_and_digest_reservations_are_atomic():
    from .test_postgres import SCHEMA
    with psycopg.connect(DSN,autocommit=True) as c:
        c.execute("ALTER TABLE public.tigerwatch_counters DROP CONSTRAINT tigerwatch_counters_resource_check")
        c.execute("ALTER TABLE public.tigerwatch_counters ADD CONSTRAINT tigerwatch_counters_resource_check CHECK(resource IN ('ai','alerts'))")
        c.execute(SCHEMA.read_text())
        c.execute(SCHEMA.read_text())
    with ThreadPoolExecutor(8) as pool:
        results=list(pool.map(lambda _:rpc("reserve",resource="digests",limit=1,interval=0)["ok"],range(16)))
    assert sum(results) == 1
    assert rpc("stats")["today"]["digests"] == 1


def test_pg_digest_actual_database_transport_with_mocked_telegram(pipeline,monkeypatch):
    from dataclasses import replace
    from tigerwatch.health import send_digest
    from tigerwatch.store import State
    from .fakes import Response
    p=pipeline
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY","test-service-role")
    class HTTP:
        def request(self,method,url,**kwargs):
            if url.startswith("https://test.supabase.co"):
                body=kwargs["json"]
                return Response(rpc(body["op"],**body["payload"]))
            return p.http.request(method,url,**kwargs)
    cfg=replace(p.cfg,supabase_url="https://test.supabase.co")
    http=HTTP()
    state=State(cfg,http)
    assert send_digest(cfg,state,http,clock=p.clock,sleep=p.clock.sleep)["status"] == "sent"
    assert send_digest(cfg,state,http,clock=p.clock,sleep=p.clock.sleep)["status"] == "already_attempted_today"
    assert p.http.count("sendMessage") == 1
    assert state.stats()["today"]["alerts"] == state.stats()["today"]["digests"] == 1


def test_pg_atomic_digest_failure_then_success_preserves_attempt():
    result=rpc("reserve_digest",limit=0,interval=4)
    assert not result["ok"] and result["resource"] == "alerts"
    assert rpc("stats")["today"].get("digests",0) == 0
    assert rpc("reserve",resource="alerts",limit=10,interval=0)["ok"]
    result=rpc("reserve_digest",limit=10,interval=60)
    assert not result["ok"] and result["reason"] == "pace"
    assert rpc("stats")["today"].get("digests",0) == 0
    with psycopg.connect(DSN) as c:
        c.execute("UPDATE public.tigerwatch_counters SET last_at=0 WHERE resource='alerts'")
    assert rpc("reserve_digest",limit=10,interval=60)["ok"]
    assert rpc("stats")["today"] == {"alerts":2,"digests":1}


def test_pg_atomic_digest_concurrent_has_one_winner():
    with ThreadPoolExecutor(8) as pool:
        results=list(pool.map(lambda _:rpc("reserve_digest",limit=10,interval=0)["ok"],range(16)))
    assert sum(results) == 1
    assert rpc("stats")["today"] == {"alerts":1,"digests":1}


def test_pg_run_lease_concurrent_and_finish_fenced():
    def begin(i):
        token=str(i)
        return token,rpc("run_begin",token=token,lease=120)
    with ThreadPoolExecutor(8) as pool:
        results=list(pool.map(begin,range(16)))
    winners=[token for token,ok in results if ok]
    assert len(winners) == 1
    assert not rpc("run_finish",token="stale",status="completed")
    with psycopg.connect(DSN) as c:
        c.execute("UPDATE public.tigerwatch_kv SET value=jsonb_set(value,'{leased_until}','0'::jsonb) WHERE key LIKE 'health/%%'")
    assert rpc("run_begin",token="replacement",lease=120)
    assert not rpc("run_finish",token=winners[0],status="completed")
    assert rpc("run_finish",token="replacement",status="partial",metrics={"claimed":1},error="meta:rate_limit")
    from tigerwatch.targets import LEGACY_SCOPE
    record=rpc("kv_get",key="health/"+LEGACY_SCOPE+"/last")
    assert record["status"] == "partial" and record["metrics"] == {"claimed":1}
    assert record["finished_at"] >= record["started_at"]
