import json
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from urllib.parse import urlsplit

import pytest

from tigerwatch.errors import ProviderError, SetupError
from tigerwatch.media import download_image
from tigerwatch.public_browser import PublicBrowser, media_key, request_allowed
from tigerwatch.worker import Worker


@pytest.mark.parametrize("url,kind,method", [
    ("https://www.instagram.com/example/", "document", "GET"),
    ("https://www.instagram.com/graphql/query", "fetch", "POST"),
    ("https://static.cdninstagram.com/app.js", "script", "GET"),
])
def test_public_network_policy_allows_normal_document_assets(url, kind, method):
    assert request_allowed(url, kind, method)


@pytest.mark.parametrize("url,kind,method", [
    ("https://scontent.cdninstagram.com/secret.jpg", "image", "GET"),
    ("https://scontent.cdninstagram.com/video.mp4", "media", "GET"),
    ("https://scontent.cdninstagram.com/unknown", "fetch", "GET"),
    ("https://www.instagram.com/image.jpg", "fetch", "GET"),
    ("https://www.instagram.com/accounts/login/", "document", "GET"),
    ("https://www.instagram.com/challenge/", "document", "GET"),
    ("https://127.0.0.1/private", "document", "GET"),
    ("http://www.instagram.com/example", "document", "GET"),
    ("https://www.instagram.com.evil.test/example", "document", "GET"),
    ("https://www.instagram.com:8080/example", "document", "GET"),
    ("https://user:pass@www.instagram.com/example", "document", "GET"),
    ("https://www.instagram.com/example", "fetch", "DELETE"),
    ("https://www.instagram.com/example", "websocket", "GET"),
])
def test_public_network_policy_blocks_media_auth_and_untrusted_hosts(url, kind, method):
    assert not request_allowed(url, kind, method)


def test_stable_link_ids_strip_tracking_parameters():
    assert media_key("https://instagram.com/p/Fixture/?x=1") == media_key("https://www.instagram.com/p/Fixture/")
    assert media_key("https://instagram.com/p/Fixture/").isdigit()
    with pytest.raises(SetupError):
        media_key("https://evil.test/p/Fixture/")


@pytest.fixture
def rendered_instagram():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception:
            pytest.skip("Chromium not installed; install it to run rendered-page integration tests")
        settings = {"count": 130, "caption": "A public fixture post", "login": False,
                    "http_status": 200, "fail_after_scroll": False, "wire": [], "closed": 0,
                    "wrong_canonical": False}
        @contextmanager
        def factory(guard):
            context = browser.new_context(accept_downloads=False, service_workers="block")
            def fixture(route):
                request = route.request
                settings["wire"].append(request.url)
                path = urlsplit(request.url).path
                if path == "/example/":
                    links = "".join(f'<a href="/p/Fixture{i}/">post</a>' for i in range(settings["count"]))
                    wall = '<input type="password">' if settings["login"] else ''
                    script = "<script>addEventListener('wheel',()=>document.body.innerHTML='<input type=password>')</script>" if settings["fail_after_scroll"] else ''
                    body = f'<html><body>{wall}{links}<a href="https://evil.test/p/Bad/">bad</a><img src="https://scontent.cdninstagram.com/blocked.jpg">{script}</body></html>'
                elif path.startswith("/p/"):
                    caption = settings["caption"]
                    canonical = '<link rel="canonical" href="https://www.instagram.com/example/">' if settings["wrong_canonical"] else ''
                    body = f'''<html><head>{canonical}<meta property="og:image" content="https://scontent.cdninstagram.com/product.jpg?secret-signature=fixture"></head>
                    <body><article><h1>{caption}</h1><img src="https://scontent.cdninstagram.com/product.jpg?secret-signature=fixture"></article></body></html>'''
                else:
                    raise AssertionError("Fixture must intercept only expected public documents; media/other requests must be blocked")
                route.fulfill(status=settings["http_status"], content_type="text/html", body=body)
            context.route("**/*", fixture)
            context.route("**/*", guard)
            page = context.new_page()
            page.set_default_timeout(5000)
            try:
                yield page
            finally:
                context.close()
                settings["closed"] += 1
        settings["factory"] = factory
        try:
            yield settings
        finally:
            browser.close()


def browser_config(p):
    return replace(p.cfg, source_kind="browser", accounts=("example",), tags=(),
                   browser_delay=0, browser_posts=120, browser_scrolls=5)


def test_rendered_browser_collects_over_100_links_without_media(pipeline, rendered_instagram):
    p, web = pipeline, rendered_instagram
    cfg = browser_config(p)
    p.state.cfg = cfg
    source = PublicBrowser(cfg, p.state, clock=p.clock, page_factory=web["factory"])
    posts = source.source("@example")
    assert len(posts) == 120 and source.last_status["reason"] == "requested_limit_reached"
    assert p.state.stats()["queue"] == {"pending": 120}
    assert all(x["needs_hydration"] and "media_url" not in x for x in posts)
    assert all("instagram.com/example/" in x for x in web["wire"])
    assert p.http.count("generateContent") == 0 and web["closed"] == 1


def test_rendered_discovery_flows_into_persistent_visual_pipeline(pipeline, rendered_instagram):
    p, web = pipeline, rendered_instagram
    web["count"] = 1
    cfg = replace(browser_config(p), alerts_enabled=False)
    p.state.cfg = cfg
    source = PublicBrowser(cfg, p.state, clock=p.clock, page_factory=web["factory"])
    worker = Worker(cfg, p.state, source, p.http, clock=p.clock, sleep=p.clock.sleep,
                    downloader=partial(download_image, resolve=lambda _: None))
    worker.run()
    ident = media_key("https://instagram.com/p/Fixture0/")
    row = p.state.inspect(ident)
    assert row["status"] == "review" and row["last_error"] == "local_match"
    assert p.http.count("generateContent") == 1 and p.http.count("api.telegram.org") == 0
    assert all("cdninstagram.com" not in url for url in web["wire"])
    before = len(web["wire"])
    worker = Worker(cfg, p.state, source, p.http, clock=p.clock, sleep=p.clock.sleep,
                    downloader=partial(download_image, resolve=lambda _: None))
    worker.run()
    assert p.http.count("generateContent") == 1 and len(web["wire"]) > before


def test_rendered_login_wall_stops_without_imported_session(pipeline, rendered_instagram):
    web = rendered_instagram
    web["login"] = True
    cfg = browser_config(pipeline)
    with pytest.raises(ProviderError, match="login_or_challenge"):
        PublicBrowser(cfg, pipeline.state, clock=pipeline.clock, page_factory=web["factory"]).source("@example")
    assert pipeline.state.stats()["queue"] == {} and web["closed"] == 1


def test_rendered_wrong_post_preview_is_not_classified(pipeline, rendered_instagram):
    p, web = pipeline, rendered_instagram
    web.update(count=1, wrong_canonical=True)
    cfg = replace(browser_config(p), alerts_enabled=False)
    p.state.cfg = cfg
    source = PublicBrowser(cfg, p.state, clock=p.clock, page_factory=web["factory"])
    Worker(cfg, p.state, source, p.http, clock=p.clock, sleep=p.clock.sleep).run()
    row = p.state.inspect(media_key("https://instagram.com/p/Fixture0/"))
    assert row["status"] == "dead" and row["last_error"] == "browser:post_identity_mismatch"
    assert p.http.count("cdninstagram.com") == p.http.count("generateContent") == 0


def test_rendered_outage_after_first_scroll_retains_already_found_links(pipeline, rendered_instagram):
    p, web = pipeline, rendered_instagram
    web.update(count=3, fail_after_scroll=True)
    cfg = replace(browser_config(p), browser_posts=100, browser_delay=0)
    p.state.cfg = cfg
    with pytest.raises(ProviderError):
        PublicBrowser(cfg, p.state, clock=p.clock, page_factory=web["factory"]).source("@example")
    assert p.state.stats()["queue"] == {"pending": 3}


def test_rendered_access_block_does_not_attempt_another_route(pipeline, rendered_instagram):
    p, web = pipeline, rendered_instagram
    web["http_status"] = 403
    with pytest.raises(ProviderError, match="access_blocked"):
        PublicBrowser(browser_config(p), p.state, clock=p.clock, page_factory=web["factory"]).source("@example")
    assert len(web["wire"]) == 1 and web["closed"] == 1


def test_rendered_post_safety_preflight_never_fetches_images_or_calls_ai(pipeline, rendered_instagram):
    p, web = pipeline, rendered_instagram
    web.update(count=1, caption="suspected child abuse reference")
    cfg = replace(browser_config(p), alerts_enabled=False)
    p.state.cfg = cfg
    source = PublicBrowser(cfg, p.state, clock=p.clock, page_factory=web["factory"])
    Worker(cfg, p.state, source, p.http, clock=p.clock, sleep=p.clock.sleep).run()
    row = p.state.inspect(media_key("https://instagram.com/p/Fixture0/"))
    assert row["status"] == "review" and row["last_error"] == "media_safety_block"
    assert not p.http.calls
    assert all("cdninstagram.com" not in url for url in web["wire"])
    assert "caption" not in json.dumps(row) and "media_url" not in json.dumps(row)


def test_pending_browser_stub_does_not_overwrite_hydrated_metadata(pipeline):
    p = pipeline
    link = "https://www.instagram.com/p/Fixture/"
    ident = media_key(link)
    hydrated = {"id": ident, "permalink": link, "media_type": "IMAGE", "media_url": "https://scontent.cdninstagram.com/current.jpg", "needs_hydration": False}
    p.state.enqueue([{"id": ident, "source": "#tiger", "data": hydrated}])
    p.state.enqueue([{"id": ident, "source": "#tiger", "data": {"id": ident, "permalink": link, "needs_hydration": True}}])
    assert p.state.inspect(ident)["data"] == hydrated
