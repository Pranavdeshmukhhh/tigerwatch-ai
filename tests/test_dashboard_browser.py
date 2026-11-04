"""Actual loopback server and Chromium; all model/provider traffic remains mocked."""
import json
import threading
from dataclasses import replace

import pytest

from tigerwatch.dashboard import BoundedDashboardServer, DashboardApp, handler_for
from tigerwatch.store import State
from tigerwatch.watches import load_watch


def test_real_dashboard_preview_save_feedback_run_and_stop(pipeline, tmp_path):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    cfg = replace(pipeline.cfg, accounts=("example",), tags=(), source_kind="browser",
                  analysis_rights_confirmed=True, alerts_enabled=False)
    calls = []
    app = DashboardApp(cfg, tmp_path / "watch.json", runner=lambda c: calls.append(c.scope) or {})
    server = None
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception:
            app.close()
            pytest.skip("Chromium unavailable in this execution environment")
        try:
            server = BoundedDashboardServer(("127.0.0.1", 0), handler_for(app, "fixture-launch-key-for-browser-tests-0123456789"))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            origin = f"http://127.0.0.1:{server.server_port}"
            page = browser.new_page()
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            page.goto(origin + "/#fixture-launch-key-for-browser-tests-0123456789")
            page.wait_for_function("() => document.querySelector('#health').textContent.includes('not_run')")
            page.locator("#profiles").fill("example")
            page.locator("#targets").fill("a red bicycle\nPikachu")
            page.locator("#exclusions").fill("toys")
            page.get_by_role("button", name="Preview interpretation").click()
            page.wait_for_function("() => !document.querySelector('#save').disabled")
            preview = json.loads(page.locator("#preview").text_content())
            assert preview["network_calls"] == 0 and len(preview["rules"]) == 2
            page.locator("#save").click()
            page.wait_for_function("() => document.querySelector('#message').textContent.includes('Watch saved')")
            chosen = load_watch(app.watch_path, cfg)
            state = State(chosen, None)
            try:
                for ident, reason in (("1001", "local_match"), ("2001", "media_safety_block")):
                    state.enqueue([{"id": ident, "source": "@example", "data": {}}])
                    item = state.claim()
                    state.save(item, release=True, status="review", last_error=reason,
                               result={"source_link": f"https://www.instagram.com/p/Fixture{ident}/",
                                       "confidence": .93, "detections": [{"id": "q1"}]})
                page.locator("#reviewfilter").select_option("unreviewed")
                page.wait_for_function("() => document.querySelector('#reviews').textContent.includes('Item 1001')")
                assert page.locator("#reviews a").count() == 1
                first = page.locator(".candidate").filter(has_text="Item 1001")
                correct = first.get_by_role("button", name="correct", exact=True)
                correct.focus()
                with page.expect_response(lambda response: response.url == origin + "/api/state") as refreshed:
                    page.locator("#reviewfilter").dispatch_event("change")
                refreshed.value.finished()
                page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                assert correct.evaluate("e => document.activeElement === e")
                first.get_by_role("button", name="correct", exact=True).click()
                page.wait_for_function("() => document.querySelector('#reviews').textContent.includes('Item 1001') === false")
                assert next(x for x in state.review_items() if x["id"] == "1001")["feedback"] == "correct"
            finally:
                state.close()
            page.locator("#run").click()
            page.wait_for_function("() => document.querySelector('#message').textContent.includes('Run started')")
            assert len(calls) == 1
            page.locator("#start").click()
            page.wait_for_function("() => document.querySelector('#control').textContent.includes('enabled')")
            page.locator("#stop").click()
            page.wait_for_function("() => document.querySelector('#message').textContent.includes('Future runs stopped')")
            assert not app.enabled
            denied = page.request.post(origin + "/api/run", data={}, headers={"Origin": "https://evil.test"})
            assert denied.status == 403
            assert all(url.startswith(origin + "/") for url in requests)
        finally:
            if server:
                server.shutdown()
                server.server_close()
            app.close()
            if app.worker_thread:
                app.worker_thread.join(3)
            browser.close()
