"""Fenced queue claims and atomic budgets; identical operations on SQLite and RPC.

No automatic RPC retry: a lost POST response may have committed a reservation.
Failing closed can under-use a budget but cannot issue an unreserved model call.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import LeaseLost, ProviderError, SetupError, StoreError
from .net import json_request, trusted_service_url
from .targets import LEGACY_SCOPE

_CACHE_MISSING = object()

TERMINAL = ("alerted", "rejected", "unsupported", "dead", "review")
SCHEMA = """
CREATE TABLE IF NOT EXISTS tigerwatch_queue (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}',
 status TEXT NOT NULL DEFAULT 'pending', progress TEXT NOT NULL DEFAULT '{}',
 result TEXT NOT NULL DEFAULT '{}', attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt REAL NOT NULL DEFAULT 0, first_seen REAL NOT NULL, updated_at REAL NOT NULL,
 lease_token TEXT, leased_until REAL NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS tw_queue_due ON tigerwatch_queue(status,next_attempt,first_seen);
CREATE TABLE IF NOT EXISTS tigerwatch_counters (
 day TEXT NOT NULL, resource TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0,
 last_at REAL NOT NULL DEFAULT 0, PRIMARY KEY(day,resource)
);
CREATE TABLE IF NOT EXISTS tigerwatch_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tigerwatch_hashtag_windows (
 account TEXT NOT NULL, tag TEXT NOT NULL, started REAL NOT NULL, PRIMARY KEY(account,tag)
);
CREATE TABLE IF NOT EXISTS tigerwatch_source_claims (source TEXT PRIMARY KEY, claimed_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tigerwatch_feedback (
 id TEXT PRIMARY KEY, verdict TEXT NOT NULL CHECK(verdict IN ('correct','incorrect','uncertain')), updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tigerwatch_image_cache (
 scope TEXT NOT NULL, key TEXT NOT NULL, decision TEXT, expires_at REAL NOT NULL DEFAULT 0,
 lease_token TEXT, leased_until REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
 PRIMARY KEY(scope,key)
);
CREATE INDEX IF NOT EXISTS tw_cache_expiry ON tigerwatch_image_cache(expires_at);

"""


class State:
    def __init__(self, cfg, http, *, clock=time.time):
        self.http, self.cfg, self.clock = http, cfg, clock
        self.remote = bool(cfg.supabase_url)
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        if bool(key) != self.remote:
            raise SetupError("Set both SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, or neither")
        if self.remote:
            cfg.require_free()
            if not trusted_service_url(cfg.supabase_url, "supabase.co"):
                raise SetupError("SUPABASE_URL must be an HTTPS *.supabase.co project origin")
            self.url = cfg.supabase_url + "/rest/v1/rpc/tigerwatch_state"
            # This project uses the legacy server-side service_role JWT, not a publishable key.
            self.headers = {"apikey": key, "Authorization": "Bearer " + key}
        else:
            if cfg.sqlite_path != ":memory:" and Path(cfg.sqlite_path).is_symlink():
                raise SetupError("Refusing a symlink state database")
            self.db = sqlite3.connect(cfg.sqlite_path, timeout=30, isolation_level=None)
            if cfg.sqlite_path != ":memory:":
                os.chmod(cfg.sqlite_path, 0o600)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=30000")
            self.db.executescript(SCHEMA)
            self._migrate_legacy()
            with self.transaction():
                self.db.execute("UPDATE tigerwatch_queue SET id=? || ':' || id WHERE instr(id,':')=0", (LEGACY_SCOPE,))

    def close(self):
        if not self.remote:
            self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _migrate_legacy(self):
        with self.transaction():
            if self.db.execute("SELECT 1 FROM tigerwatch_kv WHERE key='migration/v3'").fetchone():
                return
            tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            now = self.clock()
            if "tigerwatch_seen" in tables:
                for r in self.db.execute("SELECT id,status,source FROM tigerwatch_seen").fetchall():
                    if r["status"] in TERMINAL:
                        self.db.execute("INSERT OR IGNORE INTO tigerwatch_queue(id,source,status,first_seen,updated_at) VALUES(?,?,?,?,?)",
                                        (r["id"], r["source"], r["status"], now, now))
            if "tigerwatch_pending" in tables:
                for r in self.db.execute("SELECT * FROM tigerwatch_pending").fetchall():
                    try:
                        first = datetime.fromisoformat(r["first_seen"]).timestamp()
                        data = json.loads(r["data"])
                        if not isinstance(data, dict):
                            continue
                    except (ValueError, TypeError):
                        continue
                    self.db.execute("INSERT OR IGNORE INTO tigerwatch_queue(id,source,data,first_seen,updated_at) VALUES(?,?,?,?,?)",
                                    (r["id"], r["source"], json.dumps(data), first, now))
            if "tigerwatch_daily_usage" in tables:
                self.db.execute("INSERT OR IGNORE INTO tigerwatch_counters(day,resource,used) SELECT day,'ai',used FROM tigerwatch_daily_usage")
            self.db.execute("INSERT INTO tigerwatch_kv VALUES('migration/v3','true')")

    @staticmethod
    def decode(row):
        if row is None:
            return None
        row = dict(row)
        for field in ("data", "progress", "result"):
            if isinstance(row.get(field), str):
                row[field] = json.loads(row[field])
        return row

    def call(self, op, **payload):
        payload = dict(payload)
        payload["scope"] = self.cfg.scope
        if op in ("save", "inspect", "retry", "feedback"):
            payload["id"] = self.storage_id(payload["id"])
        if op == "enqueue":
            payload["items"] = [{**item, "id": self.storage_id(item["id"])} for item in payload["items"]]
        if self.remote:
            try:
                value = json_request(self.http, "POST", self.url, "supabase", headers=self.headers,
                                     json={"op": op, "payload": payload}, timeout=(8, 25))
            except ProviderError as exc:
                raise StoreError(f"supabase:{exc.code}; check schema, service-role key and connectivity") from None
            except Exception:
                raise StoreError("supabase:operation_failed; check schema, service-role key and connectivity") from None
            return self.logical_row(value) if op in ("claim", "inspect") else value
        with self.transaction():
            value = self._sqlite(op, payload)
            return self.logical_row(value) if op in ("claim", "inspect") else value

    def storage_id(self, media_id):
        prefix = self.cfg.scope + ":"
        if isinstance(media_id, str) and media_id.startswith(prefix):
            logical = media_id[len(prefix):]
            if not re.fullmatch(r"[0-9]{1,50}", logical):
                raise StoreError("invalid_media_id_or_target_scope")
            return media_id
        if not isinstance(media_id, str) or not re.fullmatch(r"[0-9]{1,50}", media_id):
            raise StoreError("invalid_media_id_or_target_scope")
        return prefix + media_id

    def logical_row(self, row):
        if row is None:
            return None
        if not isinstance(row, dict):
            raise StoreError("invalid_queue_row")
        row = dict(row)
        prefix = self.cfg.scope + ":"
        ident = row.get("id")
        if isinstance(ident, str) and ident.startswith(prefix):
            ident = ident[len(prefix):]
        # Never expose an accidentally cross-scoped RPC row in inspection/review.
        # Numeric IDs are also accepted for logical-row transports/test adapters.
        if not isinstance(ident, str) or not re.fullmatch(r"[0-9]{1,50}", ident):
            raise StoreError("invalid_queue_row_scope_or_id")
        row["id"] = ident
        return row

    def _sqlite(self, op, p):
        now = self.clock()
        if op == "enqueue":
            for item in p["items"]:
                self.db.execute("""INSERT INTO tigerwatch_queue(id,source,data,first_seen,updated_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    data=CASE WHEN json_extract(excluded.data,'$.needs_hydration')=1
                      AND coalesce(json_extract(tigerwatch_queue.data,'$.needs_hydration'),0)=0
                      AND json_type(tigerwatch_queue.data,'$.permalink')='text'
                      THEN tigerwatch_queue.data ELSE excluded.data END,updated_at=excluded.updated_at
                    WHERE tigerwatch_queue.status IN ('pending','retry') AND tigerwatch_queue.leased_until<=?""",
                                (item["id"], item["source"], json.dumps(item["data"]), now, now, now))
            return True
        if op == "claim":
            row = self.db.execute("""SELECT q.* FROM tigerwatch_queue q
                LEFT JOIN tigerwatch_source_claims s ON s.source=q.source
                WHERE (q.status IN ('pending','retry') OR (q.status='processing' AND q.leased_until<=?))
                AND q.next_attempt<=? AND q.leased_until<=?
                AND q.id LIKE ?
                ORDER BY coalesce(s.claimed_at,0),
                  CASE WHEN json_extract(q.result,'$.match')=1 OR q.progress<>'{}' THEN 0 ELSE 1 END,
                  q.first_seen DESC,q.id LIMIT 1""", (now, now, now, p["scope"] + ":%")).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE tigerwatch_queue SET status='processing',lease_token=?,leased_until=?,updated_at=? WHERE id=?",
                            (p["token"], now + p["lease"], now, row["id"]))
            self.db.execute("INSERT INTO tigerwatch_source_claims VALUES(?,?) ON CONFLICT(source) DO UPDATE SET claimed_at=excluded.claimed_at", (row["source"], now))
            return self.decode(self.db.execute("SELECT * FROM tigerwatch_queue WHERE id=?", (row["id"],)).fetchone())
        if op == "save":
            patch = p["patch"]
            allowed = {"data", "progress", "result", "status", "attempts", "last_error", "next_attempt"}
            if not patch or set(patch) - allowed:
                raise StoreError("invalid_queue_patch")
            assignments, values = [], []
            for k, v in patch.items():
                assignments.append(k + "=?")
                values.append(json.dumps(v) if k in ("data", "progress", "result") else v)
            if p["release"]:
                assignments += ["lease_token=NULL", "leased_until=0"]
            else:
                assignments.append("leased_until=?")
                values.append(now + p["lease"])
            assignments.append("updated_at=?")
            values += [now, p["id"], p["token"], now]
            cur = self.db.execute("UPDATE tigerwatch_queue SET " + ",".join(assignments) +
                                  " WHERE id=? AND lease_token=? AND leased_until>? AND status='processing'", values)
            return cur.rowcount == 1
        if op == "reserve":
            day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            row = self.db.execute("SELECT used,last_at FROM tigerwatch_counters WHERE day=? AND resource=?", (day, p["resource"])).fetchone()
            if p["limit"] <= 0 or (row and row["used"] >= p["limit"]):
                wait = 86400 - now % 86400 + 1
                return {"ok": False, "reason": "daily", "wait": wait}
            if row and now - row["last_at"] < p["interval"]:
                return {"ok": False, "reason": "pace", "wait": p["interval"] - (now - row["last_at"])}
            self.db.execute("INSERT INTO tigerwatch_counters(day,resource,used,last_at) VALUES(?,?,1,?) ON CONFLICT(day,resource) DO UPDATE SET used=used+1,last_at=excluded.last_at", (day, p["resource"], now))
            return {"ok": True, "reason": "reserved", "wait": 0}
        if op == "reserve_digest":
            day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            wait = 86400 - now % 86400 + 1
            digest = self.db.execute("SELECT used FROM tigerwatch_counters WHERE day=? AND resource='digests'", (day,)).fetchone()
            if digest and digest["used"] >= 1:
                return {"ok": False, "reason": "daily", "wait": wait, "resource": "digests"}
            alerts = self.db.execute("SELECT used,last_at FROM tigerwatch_counters WHERE day=? AND resource='alerts'", (day,)).fetchone()
            if p["limit"] <= 0 or (alerts and alerts["used"] >= p["limit"]):
                return {"ok": False, "reason": "daily", "wait": wait, "resource": "alerts"}
            if alerts and now - alerts["last_at"] < p["interval"]:
                return {"ok": False, "reason": "pace", "wait": p["interval"] - (now-alerts["last_at"]), "resource": "alerts"}
            for resource in ("digests", "alerts"):
                self.db.execute("INSERT INTO tigerwatch_counters(day,resource,used,last_at) VALUES(?,?,1,?) "
                                "ON CONFLICT(day,resource) DO UPDATE SET used=used+1,last_at=excluded.last_at", (day,resource,now))
            return {"ok": True, "reason": "reserved", "wait": 0, "resource": "digests"}
        if op in ("run_begin", "run_finish"):
            key = "health/" + p["scope"] + "/last"
            row = self.db.execute("SELECT value FROM tigerwatch_kv WHERE key=?", (key,)).fetchone()
            current = json.loads(row[0]) if row else {}
            current = current if isinstance(current, dict) else {}
            if op == "run_begin":
                if current.get("status") == "running" and current.get("leased_until", 0) > now:
                    return False
                record = {"id": p["token"], "started_at": now, "leased_until": now+p["lease"], "status": "running"}
            else:
                if (current.get("id") != p["token"] or current.get("status") != "running"
                        or current.get("leased_until", 0) <= now):
                    return False
                record = {**current, "finished_at": now, "status": p["status"]}
                if p.get("metrics") is not None:
                    record["metrics"] = p["metrics"]
                if p.get("error") is not None:
                    record["error"] = p["error"]
            self.db.execute("INSERT INTO tigerwatch_kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key,json.dumps(record)))
            return True
        if op == "tag":
            self.db.execute("DELETE FROM tigerwatch_hashtag_windows WHERE account=? AND started<=?", (p["account"], now - 604800))
            found = self.db.execute("SELECT 1 FROM tigerwatch_hashtag_windows WHERE account=? AND tag=?", (p["account"], p["tag"])).fetchone()
            if found:
                return True
            used = self.db.execute("SELECT count(*) FROM tigerwatch_hashtag_windows WHERE account=?", (p["account"],)).fetchone()[0]
            if used >= 30:
                return False
            self.db.execute("INSERT INTO tigerwatch_hashtag_windows VALUES(?,?,?)", (p["account"], p["tag"], now))
            return True
        if op == "kv_get":
            row = self.db.execute("SELECT value FROM tigerwatch_kv WHERE key=?", (p["key"],)).fetchone()
            return json.loads(row[0]) if row else None
        if op == "kv_set":
            self.db.execute("INSERT INTO tigerwatch_kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (p["key"], json.dumps(p["value"])))
            return True
        if op == "maintain":
            self.db.execute("""UPDATE tigerwatch_queue SET
                status=case when json_extract(result,'$.sending')=1 then 'review' else 'dead' end,
                last_error=case when json_extract(result,'$.sending')=1 then 'telegram:delivery_unknown' else 'queue_expired' end,
                data='{}',progress='{}',lease_token=NULL,leased_until=0,updated_at=?
                WHERE status IN ('pending','retry','processing') AND first_seen<? AND leased_until<=?""", (now, now - p["hours"] * 3600, now))
            self.db.execute("UPDATE tigerwatch_queue SET data='{}',progress='{}' WHERE status='review' AND first_seen<?", (now - p["hours"] * 3600,))
            self.db.execute("DELETE FROM tigerwatch_queue WHERE status IN ('alerted','rejected','unsupported','dead','review') AND updated_at<?", (now - p["days"] * 86400,))
            self.db.execute("DELETE FROM tigerwatch_counters WHERE day<?", (datetime.fromtimestamp(now - 90 * 86400, timezone.utc).date().isoformat(),))
            self.db.execute("DELETE FROM tigerwatch_feedback WHERE id NOT IN (SELECT id FROM tigerwatch_queue)")
            self.db.execute("DELETE FROM tigerwatch_image_cache WHERE expires_at<=? AND leased_until<=?", (now, now))
            return True
        if op == "stats":
            counts = {r[0]: r[1] for r in self.db.execute("SELECT status,count(*) FROM tigerwatch_queue WHERE id LIKE ? GROUP BY status", (p["scope"] + ":%",))}
            day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
            return {"queue": counts, "today": {r[0]: r[1] for r in self.db.execute("SELECT resource,used FROM tigerwatch_counters WHERE day=?", (day,))}}
        if op == "inspect":
            return self.decode(self.db.execute("SELECT * FROM tigerwatch_queue WHERE id=?", (p["id"],)).fetchone())
        if op == "review_list":
            return [self.decode(row) for row in self.db.execute(
                "SELECT q.*,f.verdict AS feedback,f.updated_at AS feedback_at FROM tigerwatch_queue q "
                "LEFT JOIN tigerwatch_feedback f ON f.id=q.id "
                "WHERE q.id LIKE ? AND q.status IN ('review','alerted') ORDER BY q.updated_at DESC LIMIT 200",
                (p["scope"] + ":%",))]
        if op == "dashboard":
            stats = self._sqlite("stats", p)
            row = self.db.execute("SELECT count(*),min(first_seen),sum(CASE WHEN next_attempt<=? AND leased_until<=? THEN 1 ELSE 0 END) "
                                  "FROM tigerwatch_queue WHERE id LIKE ? AND status IN ('pending','retry','processing')",
                                  (now, now, p["scope"] + ":%")).fetchone()
            feedback = {r[0]: r[1] for r in self.db.execute(
                "SELECT verdict,count(*) FROM tigerwatch_feedback WHERE id LIKE ? GROUP BY verdict", (p["scope"] + ":%",))}
            return {**stats, "backlog": {"pending": row[0], "due": row[2] or 0,
                    "oldest_first_seen": row[1], "oldest_age_seconds": max(0, now - row[1]) if row[1] is not None else 0},
                    "feedback": feedback}
        if op == "feedback":
            row = self.db.execute("SELECT status FROM tigerwatch_queue WHERE id=?", (p["id"],)).fetchone()
            if row is None or row[0] not in TERMINAL:
                return False
            self.db.execute("INSERT INTO tigerwatch_feedback VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET verdict=excluded.verdict,updated_at=excluded.updated_at",
                            (p["id"], p["verdict"], now))
            return True
        if op.startswith("cache_"):
            key = (p["scope"], p["key"])
            row = self.db.execute("SELECT * FROM tigerwatch_image_cache WHERE scope=? AND key=?", key).fetchone()
            if op == "cache_get":
                return json.loads(row["decision"]) if row and row["decision"] and row["expires_at"] > now else None
            if op == "cache_invalidate":
                return self.db.execute("DELETE FROM tigerwatch_image_cache WHERE scope=? AND key=? AND leased_until<=?", (*key, now)).rowcount == 1
            if op == "cache_release":
                return self.db.execute("DELETE FROM tigerwatch_image_cache WHERE scope=? AND key=? AND lease_token=?", (*key, p["token"])).rowcount == 1
            if op == "cache_commit":
                return self.db.execute("UPDATE tigerwatch_image_cache SET decision=?,expires_at=?,lease_token=NULL,leased_until=0,updated_at=? "
                                       "WHERE scope=? AND key=? AND lease_token=? AND leased_until>?",
                                       (json.dumps(p["decision"], allow_nan=False), now + 604800, now, *key, p["token"], now)).rowcount == 1
            if op == "cache_claim":
                if row and row["decision"] and row["expires_at"] > now:
                    return {"status": "hit", "value": json.loads(row["decision"])}
                if row and row["leased_until"] > now:
                    return {"status": "busy", "wait": max(1, row["leased_until"] - now)}
            elif op == "cache_put":
                if row and row["leased_until"] > now:
                    return False
            else:
                raise StoreError("unknown_cache_operation")
            count = self.db.execute("SELECT count(*) FROM tigerwatch_image_cache WHERE scope=?", (p["scope"],)).fetchone()[0]
            if row is None and count >= 5000:
                self.db.execute("DELETE FROM tigerwatch_image_cache WHERE rowid IN (SELECT rowid FROM tigerwatch_image_cache "
                                "WHERE scope=? AND leased_until<=? ORDER BY updated_at LIMIT 1)", (p["scope"], now))
                if self.db.execute("SELECT count(*) FROM tigerwatch_image_cache WHERE scope=?", (p["scope"],)).fetchone()[0] >= 5000:
                    return {"status": "busy", "wait": 60} if op == "cache_claim" else False
            if op == "cache_claim":
                self.db.execute("INSERT INTO tigerwatch_image_cache(scope,key,lease_token,leased_until,updated_at) VALUES(?,?,?,?,?) "
                                "ON CONFLICT(scope,key) DO UPDATE SET decision=NULL,expires_at=0,lease_token=excluded.lease_token,leased_until=excluded.leased_until,updated_at=excluded.updated_at",
                                (*key, p["token"], now + p["lease"], now))
                return {"status": "claimed"}
            self.db.execute("INSERT INTO tigerwatch_image_cache(scope,key,decision,expires_at,updated_at) VALUES(?,?,?,?,?) "
                            "ON CONFLICT(scope,key) DO UPDATE SET decision=excluded.decision,expires_at=excluded.expires_at,lease_token=NULL,leased_until=0,updated_at=excluded.updated_at",
                            (*key, json.dumps(p["decision"], allow_nan=False), now + 604800, now))
            return True
        if op == "retry":
            row = self.db.execute("SELECT last_error FROM tigerwatch_queue WHERE id=? AND status IN ('dead','review')", (p["id"],)).fetchone()
            if not row:
                return False
            if row[0] == "telegram:delivery_unknown" and not p["acknowledge"]:
                raise StoreError("delivery_unknown: --acknowledge-duplicate-risk required")
            self.db.execute("UPDATE tigerwatch_queue SET status='retry',attempts=0,next_attempt=0,last_error='',first_seen=?,updated_at=?,result=json_set(result,'$.sending',json('false')) WHERE id=?", (now, now, p["id"],))
            return True
        raise StoreError("unknown_state_operation")

    def enqueue(self, items):
        for start in range(0, len(items), 50):
            if self.call("enqueue", items=items[start:start + 50]) is not True:
                raise StoreError("invalid_enqueue_response")

    def claim(self):
        token = uuid4().hex
        row = self.call("claim", token=token, lease=self.cfg.lease_seconds)
        if row is not None:
            if (not isinstance(row, dict) or row.get("lease_token") != token
                    or any(not isinstance(row.get(k), dict) for k in ("data", "progress", "result"))
                    or not isinstance(row.get("id"), str) or not re.fullmatch(r"[0-9]{1,50}", row["id"])
                    or not isinstance(row.get("source"), str) or len(row["source"]) > 110
                    or type(row.get("attempts")) is not int or row["attempts"] < 0
                    or row.get("status") != "processing"):
                raise StoreError("invalid_claim_response")
        return row

    def save(self, item, *, release=False, **patch):
        ok = self.call("save", id=item["id"], token=item["lease_token"], patch=patch,
                       release=release, lease=self.cfg.lease_seconds)
        if ok is not True:
            raise LeaseLost("queue_lease_lost; stop external side effects")
        item.update(patch)

    def reserve(self, resource, limit, interval):
        if resource not in ("ai", "alerts", "digests"):
            raise StoreError("invalid_budget_resource")
        result = self.call("reserve", resource=resource, limit=limit, interval=interval)
        if (not isinstance(result, dict) or type(result.get("ok")) is not bool
                or result.get("reason") not in ("reserved", "pace", "daily")
                or type(result.get("wait")) not in (int, float) or not 0 <= result["wait"] <= 86401):
            raise StoreError("invalid_budget_response")
        return result

    def kv_get(self, key):
        return self.call("kv_get", key=key)

    def kv_set(self, key, value):
        if self.call("kv_set", key=key, value=value) is not True:
            raise StoreError("invalid_cache_response")

    def admit_tag(self, account, tag):
        value = self.call("tag", account=account, tag=tag)
        if type(value) is not bool:
            raise StoreError("invalid_hashtag_window_response")
        return value

    def maintain(self):
        return self.call("maintain", hours=self.cfg.queue_hours, days=self.cfg.dedup_days)

    def stats(self):
        return self.call("stats")

    def inspect(self, media_id):
        return self.call("inspect", id=media_id)

    def review_items(self):
        from .media import permalink
        rows = self.call("review_list")
        if not isinstance(rows, list):
            raise StoreError("invalid_review_response")
        result = []
        for row in rows:
            row = self.logical_row(row)
            data, saved = row.get("data", {}), row.get("result", {})
            result.append({"id": row["id"], "source_link": permalink(saved.get("source_link") or data.get("permalink")),
                           "reason": row["last_error"], "score": saved.get("confidence"),
                           "status": row["status"], "feedback": row.get("feedback"), "feedback_at": row.get("feedback_at"),
                           "first_seen": row["first_seen"], "updated_at": row["updated_at"],
                           "matched_query_ids": [x["id"] for x in saved.get("detections", []) if isinstance(x, dict)
                                                 and isinstance(x.get("id"), str) and re.fullmatch(r"q(?:[1-9]|10)", x["id"])],
                           "human_review_required": True, "illegality_verified": False})
        return result


    def dashboard_snapshot(self):
        value = self.call("dashboard")
        if not isinstance(value, dict) or not all(isinstance(value.get(k), dict) for k in ("queue", "today", "backlog", "feedback")):
            raise StoreError("invalid_dashboard_response")
        return value

    def set_feedback(self, media_id, verdict):
        if verdict not in ("correct", "incorrect", "uncertain"):
            raise StoreError("invalid_feedback_verdict")
        value = self.call("feedback", id=media_id, verdict=verdict)
        if type(value) is not bool:
            raise StoreError("invalid_feedback_response")
        return value

    @staticmethod
    def _cache_payload(key, token=_CACHE_MISSING, decision=_CACHE_MISSING):
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise StoreError("invalid_image_cache_key")
        value = {"key": key}
        if token is not _CACHE_MISSING:
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", token):
                raise StoreError("invalid_image_cache_token")
            value["token"] = token
        if decision is not _CACHE_MISSING:
            try:
                if not isinstance(decision, dict) or len(json.dumps(decision, allow_nan=False).encode()) > 16384:
                    raise ValueError
            except (ValueError, TypeError, RecursionError):
                raise StoreError("invalid_image_cache_decision") from None
            value["decision"] = decision
        return value

    def cache_get(self, key):
        value = self.call("cache_get", **self._cache_payload(key))
        if value is not None and not isinstance(value, dict):
            raise StoreError("invalid_image_cache_response")
        return value

    def cache_put(self, key, decision):
        return self._cache_bool("cache_put", self._cache_payload(key, decision=decision))

    def cache_claim(self, key, token, lease=120):
        if type(lease) is not int or not 60 <= lease <= 600:
            raise StoreError("invalid_image_cache_lease")
        value = self.call("cache_claim", **self._cache_payload(key, token), lease=lease)
        if not isinstance(value, dict) or value.get("status") not in ("hit", "busy", "claimed"):
            raise StoreError("invalid_image_cache_claim")
        if value["status"] == "hit" and not isinstance(value.get("value"), dict):
            raise StoreError("invalid_image_cache_claim")
        if value["status"] == "busy" and (type(value.get("wait")) not in (int, float) or not 1 <= value["wait"] <= 600):
            raise StoreError("invalid_image_cache_claim")
        return value

    def _cache_bool(self, op, payload):
        value = self.call(op, **payload)
        if type(value) is not bool:
            raise StoreError("invalid_image_cache_response")
        return value

    def cache_commit(self, key, token, decision):
        return self._cache_bool("cache_commit", self._cache_payload(key, token, decision))

    def cache_release(self, key, token):
        return self._cache_bool("cache_release", self._cache_payload(key, token))

    def cache_invalidate(self, key):
        return self._cache_bool("cache_invalidate", self._cache_payload(key))


    def reserve_digest(self, alert_limit, interval):
        if (type(alert_limit) is not int or not 0 <= alert_limit <= 200
                or type(interval) not in (int, float) or not math.isfinite(interval) or not 0 <= interval <= 60):
            raise StoreError("invalid_digest_limits")
        value = self.call("reserve_digest", limit=alert_limit, interval=interval)
        if (not isinstance(value, dict) or type(value.get("ok")) is not bool
                or value.get("reason") not in ("reserved", "pace", "daily")
                or value.get("resource") not in ("digests", "alerts")
                or type(value.get("wait")) not in (int, float) or not 0 <= value["wait"] <= 86401):
            raise StoreError("invalid_digest_reservation")
        return value

    @staticmethod
    def _run_token(token):
        if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", token):
            raise StoreError("invalid_run_token")
        return token

    def run_begin(self, token, lease=900):
        if type(lease) is not int or not 120 <= lease <= 1800:
            raise StoreError("invalid_run_lease")
        value = self.call("run_begin", token=self._run_token(token), lease=lease)
        if type(value) is not bool:
            raise StoreError("invalid_run_response")
        return value

    def run_finish(self, token, status, metrics=None, error=None):
        if status not in ("completed", "partial", "failed", "interrupted"):
            raise StoreError("invalid_run_status")
        if metrics is not None:
            if (not isinstance(metrics, dict) or len(metrics)>64
                    or any(not isinstance(k, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}",k)
                           or type(v) not in (int,float) or not math.isfinite(v) or v<0 for k,v in metrics.items())):
                raise StoreError("invalid_run_metrics")
        if error is not None and (not isinstance(error,str) or not re.fullmatch(r"[A-Za-z0-9_:.-]{1,96}",error)):
            raise StoreError("invalid_run_error")
        value = self.call("run_finish", token=self._run_token(token), status=status, metrics=metrics, error=error)
        if type(value) is not bool:
            raise StoreError("invalid_run_response")
        return value
