import email.parser
import io
import json
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tigerwatch.dashboard import DashboardApp, HTML, JS, handler_for
from tigerwatch.errors import SetupError
from tigerwatch.watches import load_watch


def rules(**extra):
    return {"profiles": ["example"], "targets": ["a red bicycle"], "source": "browser", "mode": "general", **extra}


@pytest.fixture
def app(pipeline, tmp_path):
    cfg = replace(pipeline.cfg, accounts=("example",), tags=(), source_kind="browser", alerts_enabled=False,
                  analysis_rights_confirmed=True)
    a = DashboardApp(cfg, tmp_path / "watch.json", runner=lambda cfg: {})
    yield a
    a.close()


def test_watch_preview_must_precede_save_and_never_starts_run(app):
    with pytest.raises(SetupError):
        app.save_preview("invented")
    value = app.preview(rules())
    assert not app.watch_path.exists() and not app.running
    assert app.save_preview(value["preview_id"])["saved"]
    assert load_watch(app.watch_path, app.cfg).target.description == "a red bicycle"
    with pytest.raises(SetupError):
        app.save_preview(value["preview_id"])


def test_rules_cannot_change_during_active_run(app):
    started, release, done = threading.Event(), threading.Event(), threading.Event()
    def run(cfg):
        started.set()
        release.wait(3)
        done.set()
        return {}
    app.runner = run
    token = app.preview(rules())["preview_id"]
    assert app.run_once()["started"]
    assert started.wait(1)
    assert not app.run_once()["started"]
    with pytest.raises(SetupError):
        app.save_preview(token)
    app.close()
    assert app.running and not app.enabled
    release.set()
    assert done.wait(1)


def test_automation_requires_deliberate_enable_and_bounded_interval(app):
    assert not app.enabled
    for interval in (0, 14, 1441, 15.0, True):
        with pytest.raises(SetupError):
            app.automation(True, interval)
    app.automation(True, 15)
    token = app.preview(rules())["preview_id"]
    with pytest.raises(SetupError):
        app.save_preview(token)
    app.automation(False, 15)
    assert not app.enabled and app.next_run is None


def test_secret_provider_exception_never_enters_control_status(app):
    done = threading.Event()
    def run(cfg):
        done.set()
        raise RuntimeError("private-key-and-signed-CDN-url")
    app.runner = run
    app.run_once()
    done.wait(1)
    app.worker_thread.join(2)
    assert not app.running and app.last_run["status"].startswith("failed")
    assert "private-key" not in json.dumps(app.last_run)


@pytest.fixture
def panel():
    calls = []
    app = SimpleNamespace(snapshot=lambda: {"reviews": [], "safe": True},
                          preview=lambda body: {"preview_id": "preview", "request": body},
                          run_once=lambda: calls.append("run") or {"started": True},
                          save_preview=lambda token: {"saved": token == "preview"},
                          feedback=lambda ident, verdict: {"saved": True},
                          automation=lambda enabled, interval: {"enabled": enabled})
    # Execute the actual HTTP parser/handler using in-memory wire bytes. The audit
    # sandbox forbids even AF_INET loopback sockets; no network behavior is mocked.
    origin = "http://127.0.0.1:8765"
    def fetch(path, body=None, headers=None, method=None):
        default = {"Host": "127.0.0.1:8765", "Origin": origin, "Content-Type": "application/json",
                   "X-VisualWatch-Token": "session-secret"}
        encoded = json.dumps(body).encode() if body is not None else b""
        if body is not None:
            default["Content-Length"] = str(len(encoded))
        default.update(headers or {})
        verb = method or ("POST" if body is not None else "GET")
        wire = (verb + " " + path + " HTTP/1.1\r\n" + "\r\n".join(k+": "+v for k,v in default.items()) + "\r\n\r\n").encode() + encoded
        handler = handler_for(app, "session-secret").__new__(handler_for(app, "session-secret"))
        handler.rfile, handler.wfile = io.BytesIO(wire), io.BytesIO()
        handler.server = SimpleNamespace(server_port=8765)
        handler.client_address = ("127.0.0.1", 10000)
        handler.handle_one_request()
        header, _, response = handler.wfile.getvalue().partition(b"\r\n\r\n")
        status_line, _, text_headers = header.decode().partition("\r\n")
        parsed_headers = dict(email.parser.Parser().parsestr(text_headers).items())
        return int(status_line.split()[1]), response.decode(), parsed_headers
    yield fetch, calls



def test_dashboard_is_read_only_until_authenticated_post(panel):
    fetch, calls = panel
    assert fetch("/api/state")[0] == 200
    assert fetch("/api/run", method="GET")[0] == 404
    assert not calls
    assert fetch("/api/run", {})[0] == 200 and calls == ["run"]


@pytest.mark.parametrize("headers", [
    {"Host": "evil.test"}, {"Host": "localhost"},
    {"Origin": "https://evil.test"}, {"Origin": "null"},
    {"X-VisualWatch-Token": "wrong"}, {"X-VisualWatch-Token": ""},
])
def test_cross_origin_rebinding_and_forged_tokens_are_blocked(panel, headers):
    fetch, calls = panel
    assert fetch("/api/run", {}, headers)[0] == 403
    assert calls == []


def test_html_and_scripts_cannot_load_external_media_or_execute_inline_scripts(panel):
    fetch, _ = panel
    code, _, headers = fetch("/")
    assert code == 200 and headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "img-src 'none'" in headers["Content-Security-Policy"]
    assert "innerHTML" not in JS and "<script src=\"/app.js\">" in HTML
    assert "https://" not in HTML


def test_large_non_object_and_non_json_inputs_are_rejected(panel):
    fetch, calls = panel
    assert fetch("/api/preview", {"description": "x" * 33000})[0] == 400
    assert fetch("/api/preview", ["bad"])[0] == 400
    assert fetch("/api/run", {}, {"Content-Type": "text/plain"})[0] == 400
    assert not calls


def test_unknown_fields_cannot_trigger_actions(panel):
    fetch, calls = panel
    assert fetch("/api/run", {"target": "anything"})[0] == 404
    assert not calls


def test_snapshot_does_not_expose_blocked_media_or_signed_urls(app):
    from tigerwatch.store import State
    state = State(app.cfg, None)
    try:
        state.enqueue([{"id": "1001", "source": "@example", "data": {
            "id": "1001", "permalink": "https://www.instagram.com/p/Fixture/",
            "media_url": "https://scontent.cdninstagram.com/secret.jpg?signed=secret"}}])
        row = state.claim()
        state.save(row, release=True, status="review", last_error="media_safety_block",
                   result={"source_link": "https://www.instagram.com/p/Fixture/"})
    finally:
        state.close()
    result = app.snapshot()
    assert result["reviews"][0]["source_link"] is None
    assert "signed=secret" not in json.dumps(result)
    assert "separate offline" in result["reviews"][0]["guidance"]


def test_cross_site_requests_cannot_read_review_or_session_data(panel):
    fetch, _ = panel
    assert fetch("/api/state", headers={"X-VisualWatch-Token": ""})[0] == 403
    assert fetch("/api/state", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert fetch("/api/session", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert fetch("/api/state", headers={"Origin": "https://evil.test"})[0] == 403
