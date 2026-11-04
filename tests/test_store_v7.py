from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from tigerwatch.errors import StoreError
from tigerwatch.store import State
from tigerwatch.targets import Target
from .fakes import post

KEY = "a" * 64
DECISION = {"match": False, "confidence": 0.2}


def add(p, ident="1001", source="#tiger"):
    p.state.enqueue([{"id": ident, "source": source, "data": post(ident)}])


def test_newest_first_with_source_fairness_and_saved_work_priority(pipeline):
    p = pipeline
    add(p, "1001")
    p.clock.sleep(1)
    add(p, "1002")
    p.clock.sleep(1)
    add(p, "1003", "@other")
    first = p.state.claim()
    assert first["id"] == "1003"
    second = p.state.claim()
    assert second["id"] == "1002"  # other source gets its turn
    p.state.save(second, release=True, status="retry", result={"match": True})
    assert p.state.claim()["id"] == "1002"  # saved positive before unprocessed older item


def test_feedback_is_terminal_only_and_never_requeues(pipeline):
    p = pipeline
    add(p)
    assert not p.state.set_feedback("1001", "correct")
    item = p.state.claim()
    p.state.save(item, release=True, status="alerted", result={"match": True, "source_link": post()["permalink"]})
    before = p.state.inspect("1001")
    assert p.state.set_feedback("1001", "incorrect")
    assert p.state.inspect("1001") == before
    assert p.state.review_items()[0]["feedback"] == "incorrect"
    assert p.state.set_feedback("1001", "uncertain")
    assert p.state.dashboard_snapshot()["feedback"] == {"uncertain": 1}
    assert p.state.claim() is None
    with pytest.raises(StoreError):
        p.state.set_feedback("1001", "unreviewed")


def test_dashboard_backlog_ages_due_items_and_omits_private_payload(pipeline):
    p = pipeline
    add(p)
    p.clock.sleep(10)
    item = p.state.claim()
    p.state.save(item, release=True, status="retry", next_attempt=p.clock() + 500)
    view = p.state.dashboard_snapshot()
    assert view["backlog"] == {"pending": 1, "due": 0, "oldest_first_seen": p.clock()-10, "oldest_age_seconds": 10}
    assert "media_url" not in str(view) and "permalink" not in str(view)


def test_cache_claim_commit_expiry_fencing_and_invalidate(pipeline):
    s, clock = pipeline.state, pipeline.clock
    assert s.cache_claim(KEY, "owner") == {"status": "claimed"}
    assert s.cache_claim(KEY, "second")["status"] == "busy"
    assert not s.cache_commit(KEY, "second", DECISION)
    assert not s.cache_invalidate(KEY)
    assert not s.cache_put(KEY, DECISION)
    clock.sleep(121)
    assert not s.cache_commit(KEY, "owner", DECISION)
    assert s.cache_claim(KEY, "second")["status"] == "claimed"
    assert not s.cache_release(KEY, "owner")
    assert s.cache_commit(KEY, "second", DECISION)
    assert s.cache_claim(KEY, "third") == {"status": "hit", "value": DECISION}
    assert s.cache_get(KEY) == DECISION
    assert s.cache_invalidate(KEY)
    assert s.cache_get(KEY) is None
    assert s.cache_put(KEY, DECISION)
    clock.sleep(604801)
    assert s.cache_get(KEY) is None
    assert s.cache_claim(KEY, "new")["status"] == "claimed"
    assert s.cache_release(KEY, "new")


def test_cache_and_feedback_are_scope_isolated(pipeline):
    p = pipeline
    assert p.state.cache_put(KEY, DECISION)
    add(p)
    item=p.state.claim()
    p.state.save(item, release=True, status="review")
    assert p.state.set_feedback("1001", "correct")
    other=State(replace(p.cfg, target=Target("natural_language", "red car", False)),p.http,clock=p.clock)
    try:
        assert other.cache_get(KEY) is None
        assert not other.set_feedback("1001", "incorrect")
        assert other.dashboard_snapshot()["feedback"] == {}
    finally:
        other.close()


def test_concurrent_cache_claims_have_one_winner(pipeline):
    p=pipeline
    def claim(i):
        state=State(p.cfg,p.http,clock=p.clock)
        try:
            return state.cache_claim(KEY, str(i))["status"]
        finally:
            state.close()
    with ThreadPoolExecutor(8) as pool:
        results=list(pool.map(claim,range(16)))
    assert results.count("claimed") == 1 and results.count("busy") == 15


@pytest.mark.parametrize("key", ["not-a-hash", "A"*64, "a"*63, None])
def test_cache_key_validation(pipeline,key):
    with pytest.raises(StoreError):
        pipeline.state.cache_get(key)


@pytest.mark.parametrize("decision", [None, [], {"x": float("nan")}, {"x": "x"*17000}])
def test_cache_value_validation(pipeline,decision):
    with pytest.raises(StoreError):
        pipeline.state.cache_put(KEY, decision)


def test_cache_maintenance_cleans_expired_entries_and_orphan_feedback(pipeline):
    p=pipeline
    add(p)
    item=p.state.claim()
    p.state.save(item, release=True, status="review")
    p.state.set_feedback("1001","correct")
    p.state.cache_put(KEY, DECISION)
    p.clock.sleep(p.cfg.dedup_days*86400+1)
    p.state.maintain()
    assert p.state.db.execute("SELECT count(*) FROM tigerwatch_image_cache").fetchone()[0] == 0
    assert p.state.dashboard_snapshot()["feedback"] == {}


def test_cache_capacity_evicts_completed_not_inflight_entries(pipeline):
    p=pipeline
    rows=[]
    for i in range(5000):
        rows.append((p.cfg.scope,format(i,"064x"),None if i==0 else "{}",0 if i==0 else p.clock()+604800,"owner" if i==0 else None,
                     p.clock()+120 if i==0 else 0,p.clock()+i))
    p.state.db.executemany("INSERT INTO tigerwatch_image_cache VALUES(?,?,?,?,?,?,?)",rows)
    assert p.state.cache_put("f"*64,DECISION)
    assert p.state.db.execute("SELECT count(*) FROM tigerwatch_image_cache").fetchone()[0] == 5000
    assert p.state.cache_claim("0"*64,"other")["status"] == "busy"  # active classification cannot be evicted
    assert p.state.cache_get(format(1,"064x")) is None  # oldest unleased entry evicted
    assert p.state.db.execute("SELECT lease_token FROM tigerwatch_image_cache WHERE key=?",("0"*64,)).fetchone()[0] == "owner"


def test_local_state_restricts_file_permissions_and_refuses_symlink(pipeline,tmp_path):
    import os
    from tigerwatch.errors import SetupError
    if os.name != "nt":
        assert os.stat(pipeline.cfg.sqlite_path).st_mode & 0o777 == 0o600
    link=tmp_path / "linked.sqlite3"
    try:
        link.symlink_to(pipeline.cfg.sqlite_path)
    except OSError:
        pytest.skip("Local account cannot create symlinks")
    with pytest.raises(SetupError,match="symlink"):
        State(replace(pipeline.cfg,sqlite_path=str(link)),pipeline.http)


def test_in_memory_state_remains_available(pipeline):
    state=State(replace(pipeline.cfg,sqlite_path=":memory:"),pipeline.http,clock=pipeline.clock)
    try:
        assert state.dashboard_snapshot()["queue"] == {}
    finally:
        state.close()


def test_digest_reservation_is_once_daily_and_unknown_resources_rejected(pipeline):
    p=pipeline
    assert p.state.reserve("digests",1,0)["ok"]
    assert not p.state.reserve("digests",1,0)["ok"]
    with pytest.raises(StoreError,match="resource"):
        p.state.reserve("unknown",1,0)


def test_atomic_digest_budget_and_pacing_failure_do_not_consume_attempt(pipeline):
    p=pipeline
    first=p.state.reserve_digest(0,4)
    assert first["resource"] == "alerts" and not first["ok"]
    assert p.state.stats()["today"].get("digests",0) == p.state.stats()["today"].get("alerts",0) == 0
    assert p.state.reserve("alerts",10,0)["ok"]
    pace=p.state.reserve_digest(10,4)
    assert pace["reason"] == "pace" and pace["resource"] == "alerts"
    assert p.state.stats()["today"].get("digests",0) == 0
    p.clock.sleep(5)
    assert p.state.reserve_digest(10,4)["ok"]
    again=p.state.reserve_digest(10,4)
    assert not again["ok"] and again["resource"] == "digests"
    assert p.state.stats()["today"] == {"alerts":2,"digests":1}


def test_concurrent_atomic_digest_has_one_winner_and_one_alert(pipeline):
    p=pipeline
    def reserve(_):
        state=State(p.cfg,p.http,clock=p.clock)
        try:
            return state.reserve_digest(10,0)["ok"]
        finally:
            state.close()
    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(reserve,range(16))) == 1
    assert p.state.stats()["today"] == {"alerts":1,"digests":1}


def test_scope_run_lease_fences_finish_and_allows_expired_recovery(pipeline):
    p=pipeline
    assert p.state.run_begin("first",lease=120)
    assert not p.state.run_begin("second",lease=120)
    assert not p.state.run_finish("other","completed")
    p.clock.sleep(121)
    assert not p.state.run_finish("first","completed")
    assert p.state.run_begin("second",lease=120)
    assert not p.state.run_finish("first","failed",error="OldError")
    assert p.state.run_finish("second","partial",metrics={"claimed":1},error="meta:rate_limit")
    record=p.state.kv_get("health/"+p.cfg.scope+"/last")
    assert record["id"] == "second" and record["status"] == "partial" and record["finished_at"] == p.clock()
    assert not p.state.run_finish("second","completed")
    assert p.state.run_begin("third",lease=120)


def test_concurrent_run_begin_has_one_winner(pipeline):
    p=pipeline
    def begin(i):
        state=State(p.cfg,p.http,clock=p.clock)
        try:
            return state.run_begin(str(i))
        finally:
            state.close()
    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(begin,range(16))) == 1


@pytest.mark.parametrize("kwargs", [{"status":"invented"},{"status":"completed","error":"https://secret.test"},
                                    {"status":"completed","metrics":{"secret":"text"}},
                                    {"status":"completed","metrics":{"calls":float("nan")}}])
def test_run_finish_rejects_untrusted_diagnostics(pipeline,kwargs):
    with pytest.raises(StoreError):
        pipeline.state.run_finish("owner",**kwargs)
