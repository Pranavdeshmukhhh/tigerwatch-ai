"""Private loopback-only control panel. No third-party assets or media previews."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .dashboard_assets import HTML, CSS, JS
from .errors import SetupError, TigerWatchError
from .rules import config_from_rules, preview_rules, watch_value
from .watches import load_watch, save_watch

MAX_BODY = 32_000
MAX_HEADERS = 16_000


def _run_monitor(cfg):
    from .health import run_monitor
    from .meta import Meta
    from .net import session
    from .public_browser import PublicBrowser
    from .store import State
    cfg.require_monitor()
    http = session()
    state = None
    try:
        state = State(cfg, http)
        source = PublicBrowser(cfg, state) if cfg.source_kind == "browser" else Meta(cfg, http, state)
        return run_monitor(cfg, state, source, http)
    finally:
        if state:
            state.close()
        http.close()


class DashboardApp:
    def __init__(self, cfg, watch_path="watch.json", *, runner=None):
        self.cfg, self.watch_path = cfg, Path(watch_path)
        self.runner = runner or _run_monitor
        self.lock = threading.RLock()
        self.running, self.enabled, self.closed = False, False, False
        self.interval_minutes, self.next_run = 60, None
        self.last_run = None
        self.worker_thread = None
        self.preview_id, self.preview_payload, self.preview_revision = None, None, None
        self.stop = threading.Event()
        self.scheduler = threading.Thread(target=self._schedule, daemon=True)
        self.scheduler.start()

    def configuration(self):
        if self.watch_path.is_symlink():
            raise SetupError("Refusing a symlink watch file")
        return load_watch(self.watch_path, self.cfg) if self.watch_path.exists() else self.cfg

    def snapshot(self):
        from .health import build_summary
        from .net import session
        from .store import State
        with self.lock:
            cfg = self.configuration()
            control = {"running": self.running, "automation_enabled": self.enabled,
                       "interval_minutes": self.interval_minutes, "next_run": self.next_run,
                       "last_run": self.last_run, "computer_must_stay_on": True}
            watch = watch_value(cfg)
        http, state = session(), None
        try:
            state = State(cfg, http)
            summary = build_summary(cfg, state, expected_interval=control["interval_minutes"] * 60 if control["automation_enabled"] else 3600)
            reviews = state.review_items()
            reviews = [{**row, "source_link": None,
                        "guidance": "Use the separate offline URL-only reporting workflow; media was not processed"}
                       if row.get("reason") == "media_safety_block" else row for row in reviews]
        except TigerWatchError:
            summary = {"diagnostic": "State unavailable; check database credentials, migration and free-plan configuration"}
            reviews = []
        finally:
            if state:
                state.close()
            http.close()
        return {"watch": watch, "scope": cfg.scope, "health": summary, "reviews": reviews, "control": control,
                "secrets_editable": False, "media_previews": False}

    def _revision(self):
        if self.watch_path.is_symlink():
            raise SetupError("Refusing a symlink watch file")
        try:
            with self.watch_path.open("rb") as stream:
                data = stream.read(MAX_BODY + 1)
            if len(data) > MAX_BODY:
                raise SetupError("Watch file exceeds 32 KB")
            return hashlib.sha256(data).hexdigest()
        except FileNotFoundError:
            return None

    def preview(self, payload):
        with self.lock:
            if self.closed:
                raise SetupError("Dashboard is closed")
            result = preview_rules(self.cfg, payload)
            self.preview_revision = self._revision()
            self.preview_id = secrets.token_urlsafe(24)
            self.preview_payload = json.loads(json.dumps(payload))
            return {**result, "preview_id": self.preview_id}

    def save_preview(self, ident):
        with self.lock:
            if self.closed or self.running or self.enabled:
                raise SetupError("Stop local automation and let active work finish before changing the watch")
            if not _same_token(ident, self.preview_id):
                raise SetupError("Preview the rules before saving")
            if self._revision() != self.preview_revision:
                raise SetupError("Watch changed in another editor; preview the current rules again")
            chosen = config_from_rules(self.cfg, self.preview_payload)
            save_watch(self.watch_path, chosen)
            self.preview_id, self.preview_payload, self.preview_revision = None, None, None
            return {"saved": True, "watch": watch_value(chosen)}

    def feedback(self, ident, verdict, scope=None):
        from .net import session
        from .store import State
        with self.lock:
            if self.closed:
                raise SetupError("Dashboard is closed")
            cfg = self.configuration()
            if not isinstance(scope, str) or scope != cfg.scope:
                raise SetupError("Watch changed; refresh the inbox before recording feedback")
            # Keep the scope selection and write together relative to dashboard saves.
            http, state = session(), None
            try:
                state = State(cfg, http)
                return {"saved": state.set_feedback(ident, verdict)}
            finally:
                if state:
                    state.close()
                http.close()

    def run_once(self):
        def execute():
            status = "completed"
            try:
                value = self.runner(cfg)
                if isinstance(value, dict) and value.get("monitor_busy"):
                    status = "another_monitor_is_active"
                if isinstance(value, dict) and (value.get("source_errors") or value.get("stopped")):
                    status = "attention_required"
            except Exception:
                status = "failed; inspect CLI diagnostics and health summary"
            finally:
                with self.lock:
                    self.running = False
                    self.last_run = {"finished_at": time.time(), "status": status}
        with self.lock:
            if self.closed or self.running:
                return {"started": False, "reason": "already_running_or_closed"}
            cfg = self.configuration()
            cfg.require_monitor()
            self.running = True
            self.worker_thread = threading.Thread(target=execute, daemon=False)
            try:
                # Closing or saving cannot race between acceptance and thread start.
                self.worker_thread.start()
            except Exception:
                self.running, self.worker_thread = False, None
                raise
            return {"started": True}

    def automation(self, enabled, interval=60):
        if type(enabled) is not bool or type(interval) is not int or not 15 <= interval <= 1440:
            raise SetupError("Automation interval must be 15–1440 minutes and enabled must be a boolean")
        with self.lock:
            if self.closed:
                raise SetupError("Dashboard is closed")
            if enabled:
                self.configuration().require_monitor()
            was_enabled = self.enabled
            changed_interval = interval != self.interval_minutes
            self.enabled, self.interval_minutes = enabled, interval
            if not enabled:
                self.next_run = None
            elif not was_enabled:
                self.next_run = time.time()
            elif changed_interval:
                self.next_run = time.time() + interval * 60
        return {"enabled": enabled, "interval_minutes": interval,
                "active_run_finishes": True, "computer_must_stay_on": True}

    def _schedule(self):
        while not self.stop.wait(0.25):
            with self.lock:
                due = self.enabled and not self.closed and self.next_run <= time.time()
                if due:
                    self.next_run = time.time() + self.interval_minutes * 60
            if due:
                try:
                    self.run_once()
                except Exception:
                    with self.lock:
                        self.enabled, self.next_run = False, None
                        self.last_run = {"finished_at": time.time(), "status": "configuration_requires_attention"}

    def close(self):
        with self.lock:
            self.closed, self.enabled, self.next_run = True, False, None
        self.stop.set()
        self.scheduler.join(timeout=1)


def _same_token(actual, expected):
    if not isinstance(actual, str) or not isinstance(expected, str) or not expected or len(actual) > 128:
        return False
    try:
        return hmac.compare_digest(actual.encode("ascii"), expected.encode("ascii"))
    except UnicodeError:
        return False


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _json_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _json_integer(value):
    if len(value) > 20:
        raise ValueError("oversized integer")
    return int(value)


def _json_constant(value):
    raise ValueError("non-standard JSON constant")


class RequestBudget:
    """Fixed buckets only; bounds local request work without storing client data."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.lock, self.windows = clock, threading.Lock(), {}

    def allow(self, bucket, limit, window=60):
        with self.lock:
            now = self.clock()
            began, count = self.windows.get(bucket, (now, 0))
            if now - began >= window:
                began, count = now, 0
            self.windows[bucket] = (began, count + 1)
            return count < limit


class BoundedDashboardServer(ThreadingHTTPServer):
    """Loopback-only server with bounded simultaneous handlers and socket waits."""
    daemon_threads = True
    request_queue_size = 12
    allow_reuse_address = True

    def __init__(self, address, handler, *, max_connections=12):
        if address[0] != "127.0.0.1" or not 1 <= max_connections <= 32:
            raise SetupError("Dashboard must bind only to loopback with bounded connections")
        self.slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Raw handler exceptions can contain private paths, headers or URL text.
        pass


def handler_for(app, token):
    budget = RequestBudget()
    class Handler(BaseHTTPRequestHandler):
        server_version = "VisualWatchLocal"
        sys_version = ""
        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def parse_request(self):
            if not super().parse_request():
                return False
            if len(self.raw_requestline) > 2048 or sum(len(k) + len(v) + 4 for k, v in self.headers.items()) > MAX_HEADERS:
                self._send(431, {"error": "Request headers exceed local limits"})
                return False
            singular = ("Host", "Origin", "X-VisualWatch-Token", "Content-Type", "Content-Length",
                        "Transfer-Encoding", "Sec-Fetch-Site", "Expect")
            if any(len(self.headers.get_all(name, [])) > 1 for name in singular):
                self._send(400, {"error": "Ambiguous duplicate headers"})
                return False
            if self.headers.get("Expect"):
                self._send(417, {"error": "Expect is not supported"})
                return False
            return True

        def _host_allowed(self):
            return self.headers.get("Host") == "127.0.0.1:" + str(self.server.server_port)

        def _send(self, status, value, kind="application/json"):
            self.close_connection = True
            body = json.dumps(value, ensure_ascii=True, allow_nan=False).encode() if kind == "application/json" else value.encode()
            self.send_response(status)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'")
            if status == 429:
                self.send_header("Retry-After", "60")
            self.end_headers()
            self.wfile.write(body)

        def _auth(self, *, write=False):
            expected = "http://127.0.0.1:" + str(self.server.server_port)
            if (not self._host_allowed() or self.headers.get("Origin") not in ((expected,) if write else (None, expected))
                    or self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none")
                    or not _same_token(self.headers.get("X-VisualWatch-Token", ""), token)):
                status = 403 if budget.allow("failed_auth", 20) else 429
                self._send(status, {"error": "Open the private launch link from your terminal"})
                return False
            if not budget.allow("writes" if write else "reads", 60 if write else 120):
                self._send(429, {"error": "Local request limit reached; wait before trying again"})
                return False
            return True

        def do_GET(self):
            if not self._host_allowed():
                return self._send(403, {"error": "Loopback host required"})
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length") not in (None, "0"):
                return self._send(400, {"error": "GET must not include a body"})
            if self.headers.get("Origin") not in (None, "http://" + self.headers["Host"]):
                return self._send(403, {"error": "Same origin required"})
            routes = {"/": (HTML, "text/html"), "/style.css": (CSS, "text/css"), "/app.js": (JS, "text/javascript")}
            if self.path in routes:
                value, kind = routes[self.path]
                return self._send(200, value, kind)
            if self.path.startswith("/api/") and not self._auth():
                return
            if self.path == "/api/session":
                return self._send(200, {"token": token})
            if self.path == "/api/state":
                try:
                    return self._send(200, app.snapshot())
                except Exception:
                    return self._send(503, {"error": "State unavailable; inspect local configuration and migration"})
            return self._send(404, {"error": "Not found"})

        def do_POST(self):
            if not self._auth(write=True):
                return
            if (self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding")
                    or len(self.headers.get_all("Content-Length", [])) != 1):
                return self._send(400, {"error": "Use bounded JSON with Content-Length"})
            try:
                raw_size = self.headers.get("Content-Length", "")
                if not raw_size.isascii() or not raw_size.isdecimal() or len(raw_size) > 5:
                    raise ValueError
                size = int(raw_size)
                if not 0 < size <= MAX_BODY:
                    raise ValueError
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError
                body = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_pairs,
                                  parse_float=_json_number, parse_int=_json_integer, parse_constant=_json_constant)
                if not isinstance(body, dict):
                    raise ValueError
            except (ValueError, UnicodeError, RecursionError, TimeoutError, OSError):
                return self._send(400, {"error": "Invalid JSON body or size"})
            try:
                if self.path == "/api/preview":
                    value = app.preview(body)
                elif self.path == "/api/save" and set(body) == {"preview_id"}:
                    value = app.save_preview(body["preview_id"])
                elif self.path == "/api/run" and body == {}:
                    value = app.run_once()
                elif self.path == "/api/feedback" and set(body) == {"id", "verdict", "scope"}:
                    value = app.feedback(body["id"], body["verdict"], body["scope"])
                elif self.path == "/api/automation" and set(body) == {"enabled", "interval_minutes"}:
                    value = app.automation(body["enabled"], body["interval_minutes"])
                else:
                    return self._send(404, {"error": "Unknown action or invalid fields"})
                return self._send(200, value)
            except TigerWatchError as exc:
                return self._send(400, {"error": str(exc)})
            except Exception:
                return self._send(503, {"error": "Action unavailable; inspect local configuration and database migration"})

        def do_OPTIONS(self):
            return self._send(405, {"error": "Cross-origin access is not supported"})

        do_TRACE = do_OPTIONS
        do_PUT = do_OPTIONS
        do_DELETE = do_OPTIONS
    return Handler


def serve_dashboard(cfg, http=None, watch_path="watch.json", port=8765):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise SetupError("Dashboard port must be 1024–65535")
    app = DashboardApp(cfg, watch_path)
    server = None
    try:
        token = secrets.token_urlsafe(32)
        server = BoundedDashboardServer(("127.0.0.1", port), handler_for(app, token))
        print(f"Private dashboard: http://127.0.0.1:{port}/#{token}")
        print("Keep the launch link private. It grants local control for this launch only.")
        print("No watch starts until you choose Run or Start local automation. Keep this terminal/computer on.")
        server.serve_forever(poll_interval=0.25)
    finally:
        app.close()
        if server:
            server.server_close()
