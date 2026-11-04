"""Wire-level local dashboard security, with no production credentials or sockets."""
import email.parser
import io
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tigerwatch import dashboard
from tigerwatch.dashboard import BoundedDashboardServer, DashboardApp, RequestBudget, handler_for
from tigerwatch.errors import SetupError
from tigerwatch.watches import save_watch


@pytest.fixture
def wire():
    calls = []
    app = SimpleNamespace(snapshot=lambda: calls.append("snapshot") or {"private": "review data"},
                          preview=lambda value: calls.append("preview") or value,
                          run_once=lambda: calls.append("run") or {"started": True},
                          feedback=lambda *args: calls.append(args) or {"saved": True})
    Handler = handler_for(app, "private-launch-key")
    def send(path="/api/state", *, method="GET", body=b"", overrides=None, extra=()):
        headers = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765",
                   "X-VisualWatch-Token": "private-launch-key"}
        if method == "POST":
            headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
        for key, value in (overrides or {}).items():
            if value is None:
                headers.pop(key, None)
            else:
                headers[key] = value
        lines = list(headers.items()) + list(extra)
        request = (method + " " + path + " HTTP/1.1\r\n" + "\r\n".join(k + ": " + v for k, v in lines) + "\r\n\r\n").encode("latin1") + body
        h = Handler.__new__(Handler)
        h.rfile, h.wfile = io.BytesIO(request), io.BytesIO()
        h.server = SimpleNamespace(server_port=8765)
        h.client_address = ("127.0.0.1", 12345)
        h.handle_one_request()
        raw_headers, _, raw_body = h.wfile.getvalue().partition(b"\r\n\r\n")
        line, _, rest = raw_headers.decode().partition("\r\n")
        response_headers = dict(email.parser.Parser().parsestr(rest).items())
        return int(line.split()[1]), raw_body.decode(), response_headers
    return send, calls


@pytest.mark.parametrize("path", ["/api/session", "/api/state", "/api/unknown"])
def test_every_api_requires_private_launch_key(wire, path):
    send, calls = wire
    code, body, _ = send(path, overrides={"X-VisualWatch-Token": None, "Origin": None})
    assert code == 403 and "private-launch-key" not in body and not calls


def test_authenticated_session_can_bootstrap_but_root_has_no_key(wire):
    send, _ = wire
    assert json.loads(send("/api/session")[1])["token"] == "private-launch-key"
    code, body, _ = send("/", overrides={"X-VisualWatch-Token": None})
    assert code == 200 and "private-launch-key" not in body and "review data" not in body


@pytest.mark.parametrize("path", ["/.env", "/schema.sql", "/tigerwatch/dashboard.py", "/../.env", "/%2e%2e/.env", "/app.js/../../.env"])
def test_static_routes_cannot_read_project_files(wire, path):
    send, calls = wire
    code, body, _ = send(path, overrides={"X-VisualWatch-Token": None})
    assert code == 404 and "private-launch-key" not in body and not calls


@pytest.mark.parametrize("name,value", [
    ("Host", "evil.test"), ("host", "127.0.0.1:8765"),
    ("Origin", "http://127.0.0.1:8765"), ("X-VisualWatch-Token", "private-launch-key"),
    ("Content-Length", "2"), ("Content-Type", "application/json"),
    ("Transfer-Encoding", "chunked"), ("Sec-Fetch-Site", "same-origin"),
])
def test_duplicate_security_and_framing_headers_rejected(wire, name, value):
    send, calls = wire
    extra = [(name, value)]
    overrides = {}
    if name == "Transfer-Encoding":
        overrides[name] = "chunked"
    if name == "Sec-Fetch-Site":
        overrides[name] = "same-origin"
    assert send("/api/run", method="POST", body=b"{}", overrides=overrides, extra=extra)[0] == 400
    assert not calls


@pytest.mark.parametrize("token", ["", "wrong", "caf\xe9", "x" * 200])
def test_invalid_non_ascii_and_long_tokens_fail_without_exception(wire, token):
    send, calls = wire
    assert send(overrides={"X-VisualWatch-Token": token})[0] == 403 and not calls


@pytest.mark.parametrize("body", [b'{"profiles":[],"profiles":["example"]}', b'{"x":NaN}',
                                  b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e9999}',
                                  b'{"x":123456789012345678901}', b'[1]', b'{bad', b'\xff'])
def test_ambiguous_or_non_standard_json_cannot_reach_actions(wire, body):
    send, calls = wire
    assert send("/api/preview", method="POST", body=body)[0] == 400 and not calls


@pytest.mark.parametrize("length", ["-1", "+2", "2x", "99999999", "0"])
def test_invalid_content_lengths_rejected(wire, length):
    send, calls = wire
    assert send("/api/run", method="POST", body=b"{}", overrides={"Content-Length": length})[0] == 400
    assert not calls


def test_truncated_body_and_get_payload_rejected(wire):
    send, calls = wire
    assert send("/api/run", method="POST", body=b"{", overrides={"Content-Length": "2"})[0] == 400
    assert send(overrides={"Content-Length": "2"}, body=b"{}")[0] == 400
    assert not calls


def test_failed_auth_is_rate_limited_without_locking_out_valid_key(wire):
    send, calls = wire
    for _ in range(20):
        assert send(overrides={"X-VisualWatch-Token": "bad"})[0] == 403
    code, body, headers = send(overrides={"X-VisualWatch-Token": "bad"})
    assert code == 429 and headers["Retry-After"] == "60" and "private-launch-key" not in body
    assert send()[0] == 200 and calls == ["snapshot"]


def test_authenticated_read_work_is_bounded(wire):
    send, calls = wire
    for _ in range(120):
        assert send()[0] == 200
    assert send()[0] == 429 and len(calls) == 120


def test_response_policy_disallows_frames_capabilities_and_external_resources(wire):
    send, _ = wire
    _, _, headers = send("/")
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=()" in headers["Permissions-Policy"] and "geolocation=()" in headers["Permissions-Policy"]
    assert "object-src 'none'" in headers["Content-Security-Policy"]
    assert headers["Connection"] == "close" and headers["Cache-Control"] == "no-store"


def test_no_cors_preflight_or_trace(wire):
    send, calls = wire
    for method in ("OPTIONS", "TRACE", "PUT", "DELETE"):
        code, _, headers = send(method=method)
        assert code == 405 and "Access-Control-Allow-Origin" not in headers
    assert not calls


def test_missing_or_stale_feedback_scope_cannot_change_new_watch(wire):
    send, calls = wire
    body = json.dumps({"id": "1001", "verdict": "correct"}).encode()
    assert send("/api/feedback", method="POST", body=body)[0] == 404 and not calls
    body = json.dumps({"id": "1001", "verdict": "correct", "scope": "watch"}).encode()
    assert send("/api/feedback", method="POST", body=body)[0] == 200
    assert calls == [("1001", "correct", "watch")]


@pytest.fixture
def app(pipeline, tmp_path):
    cfg = replace(pipeline.cfg, accounts=("example",), tags=(), source_kind="browser", alerts_enabled=False,
                  analysis_rights_confirmed=True)
    result = DashboardApp(cfg, tmp_path / "watch.json", runner=lambda c: {})
    yield result
    result.close()


def _rules(target="a red bicycle"):
    return {"profiles": ["example"], "targets": [target], "source": "browser", "mode": "general"}


def test_another_editor_change_requires_fresh_preview(app):
    preview = app.preview(_rules())
    save_watch(app.watch_path, replace(app.cfg, accounts=("other",)))
    with pytest.raises(SetupError, match="another editor"):
        app.save_preview(preview["preview_id"])
    assert 'other' in app.watch_path.read_text()


def test_watch_change_refuses_stale_inbox_feedback(app):
    old_scope = app.configuration().scope
    preview = app.preview(_rules("a green balloon"))
    app.save_preview(preview["preview_id"])
    with pytest.raises(SetupError, match="Watch changed"):
        app.feedback("1001", "correct", old_scope)


def test_closed_dashboard_refuses_edits_and_execution(app):
    app.close()
    with pytest.raises(SetupError, match="closed"):
        app.preview(_rules())
    with pytest.raises(SetupError, match="closed"):
        app.feedback("1001", "correct", app.cfg.scope)
    assert not app.run_once()["started"]


def test_repeated_start_does_not_reset_next_run(app):
    # Hold the app lock so its scheduler cannot run between control assertions.
    with app.lock:
        app.automation(True, 60)
        app.next_run = 9876543210
        app.automation(True, 60)
        assert app.next_run == 9876543210


def test_request_budget_recovers_after_window():
    moment = [0]
    budget = RequestBudget(clock=lambda: moment[0])
    assert budget.allow("reads", 1)
    assert not budget.allow("reads", 1)
    moment[0] = 60
    assert budget.allow("reads", 1)


def test_server_rejects_public_interface_before_opening_socket():
    with pytest.raises(SetupError, match="loopback"):
        BoundedDashboardServer(("0.0.0.0", 8765), None)


def test_start_failure_rolls_back_active_flag(app, monkeypatch):
    def fail(_):
        raise RuntimeError("cannot start")
    monkeypatch.setattr(dashboard.threading.Thread, "start", fail)
    with pytest.raises(RuntimeError):
        app.run_once()
    assert not app.running and app.worker_thread is None


def test_private_launch_link_has_unlogged_fragment(pipeline, tmp_path, monkeypatch, capsys):
    created = []
    class StubServer:
        def __init__(self, address, handler):
            created.append((address, handler))
        def serve_forever(self, **kw):
            pass
        def server_close(self):
            pass
    monkeypatch.setattr(dashboard, "BoundedDashboardServer", StubServer)
    dashboard.serve_dashboard(pipeline.cfg, watch_path=tmp_path / "watch.json")
    line = capsys.readouterr().out.splitlines()[0]
    assert line.startswith("Private dashboard: http://127.0.0.1:8765/#")
    assert len(line.split("#", 1)[1]) >= 40
    assert created[0][0] == ("127.0.0.1", 8765)


def test_connection_slots_reject_excess_work_without_spawning(monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    server = BoundedDashboardServer.__new__(BoundedDashboardServer)
    server.slots = threading.BoundedSemaphore(1)
    started, closed = [], []
    monkeypatch.setattr(ThreadingHTTPServer, "process_request", lambda self, request, address: started.append(request))
    server.shutdown_request = lambda request: closed.append(request)
    server.process_request("active", ("127.0.0.1", 1))
    server.process_request("excess", ("127.0.0.1", 2))
    assert started == ["active"] and closed == ["excess"]
    server.slots.release()
    server.process_request("next", ("127.0.0.1", 3))
    assert started == ["active", "next"]


def test_dashboard_refuses_symlink_watch_reads(app, tmp_path):
    target = tmp_path / "private-watch.json"
    save_watch(target, app.cfg)
    try:
        app.watch_path.symlink_to(target)
    except OSError:
        pytest.skip("Local account cannot create symlinks")
    with pytest.raises(SetupError, match="symlink"):
        app.configuration()
