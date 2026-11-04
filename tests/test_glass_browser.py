"""Rendered glass UI, access boundaries and accessibility against a local fixture."""
import json
import threading
from dataclasses import replace

import pytest

from tigerwatch.dashboard import BoundedDashboardServer, DashboardApp, handler_for


@pytest.fixture
def glass_panel(pipeline, tmp_path):
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
            yield browser, f"http://127.0.0.1:{server.server_port}", calls
        finally:
            if server:
                server.shutdown()
                server.server_close()
            app.close()
            if app.worker_thread:
                app.worker_thread.join(3)
            browser.close()


def unlock(page, origin):
    page.goto(origin + "/#fixture-launch-key-for-browser-tests-0123456789")
    page.wait_for_function("() => document.querySelector('#health').textContent.includes('not_run')")


def test_private_key_is_required_removed_and_not_persisted(glass_panel):
    browser, origin, calls = glass_panel
    page = browser.new_page()
    urls = []
    page.on("request", lambda r: urls.append(r.url))
    page.goto(origin)
    page.wait_for_function("() => !document.querySelector('#locked').hidden")
    assert page.request.get(origin + "/api/session").status == 403
    assert page.request.get(origin + "/api/state").status == 403
    unlock(page, origin)
    assert page.url == origin + "/"
    assert "fixture-launch-key-for-browser-tests-0123456789" not in page.content()
    assert page.evaluate("() => [localStorage.length, sessionStorage.length]") == [0, 0]
    assert not any("fixture-launch-key-for-browser-tests-0123456789" in url for url in urls)
    assert not calls
    page.reload()
    page.wait_for_function("() => !document.querySelector('#locked').hidden")


@pytest.mark.parametrize("width,theme", [(390, "light"), (390, "dark"), (1440, "light"), (1440, "dark")])
def test_responsive_glass_has_no_overflow_and_touch_controls(glass_panel, width, theme):
    browser, origin, _ = glass_panel
    context = browser.new_context(viewport={"width": width, "height": 960}, color_scheme=theme)
    page = context.new_page()
    unlock(page, origin)
    assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1")
    for selector in ("#run", "#start", "#stop", "#profiles", "#targets", "#source", "#preview-button"):
        box = page.locator(selector).bounding_box()
        assert box and box["height"] >= 44, selector
    context.close()


def test_reduced_motion_transparency_and_forced_colors(glass_panel):
    browser, origin, _ = glass_panel
    context = browser.new_context(viewport={"width": 390, "height": 960}, reduced_motion="reduce")
    page = context.new_page()
    unlock(page, origin)
    durations = page.locator(".panel").first.evaluate("e => [getComputedStyle(e).animationDuration,getComputedStyle(e).transitionDuration]")
    assert all(float(x.rstrip("ms")) <= .01 for x in durations)
    cdp = context.new_cdp_session(page)
    cdp.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]})
    assert page.locator(".glass").first.evaluate("e => getComputedStyle(e).backdropFilter") == "none"
    page.emulate_media(forced_colors="active")
    assert page.locator(".glass").first.evaluate("e => getComputedStyle(e).backdropFilter") == "none"
    context.close()


def test_description_is_literal_and_dirty_form_survives_refresh(glass_panel):
    browser, origin, calls = glass_panel
    page = browser.new_page()
    unlock(page, origin)
    literal = '<img src=x onerror="document.body.dataset.pwned=1">'
    page.locator("#targets").fill(literal)
    page.get_by_role("button", name="Preview interpretation").click()
    page.wait_for_function("() => !document.querySelector('#save').disabled")
    preview = json.loads(page.locator("#preview").text_content())
    assert preview["rules"][0]["description"] == literal
    assert page.locator("img").count() == 0
    assert page.evaluate("() => document.body.dataset.pwned") is None
    page.locator("#profiles").fill("another_authorized_profile")
    with page.expect_response(lambda r: r.url == origin + "/api/state"):
        page.locator("#reviewfilter").select_option("unreviewed")
    assert page.locator("#profiles").input_value() == "another_authorized_profile"
    assert page.locator("#targets").input_value() == literal
    assert page.locator("#save").is_disabled() and not calls
