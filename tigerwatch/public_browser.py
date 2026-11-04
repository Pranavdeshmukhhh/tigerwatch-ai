"""Bounded logged-out public Instagram discovery, without access-control bypass.

Browsers collect metadata only: image/video requests are blocked. Only the worker
may later fetch an approved image, after explicit query/content safety checks.
No password, imported cookie, saved session, stealth plugin or proxy rotation.
"""
from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from .errors import ProviderError, SetupError
from .media import approved_cdn, permalink
from .net import retry_after, secure_url
from .safety import child_safety_request, sale_signals
from .watches import profile_handle


def media_key(url):
    canonical = permalink(url)
    if not canonical:
        raise SetupError("Invalid Instagram post link")
    return str(int(hashlib.sha256(canonical.encode()).hexdigest(), 16) % (10 ** 48))


def request_allowed(url, resource_type, method="GET"):
    p = secure_url(url)
    if not p or method not in ("GET", "POST", "OPTIONS"):
        return False
    if resource_type in ("image", "media", "font", "websocket", "eventsource"):
        return False
    if p.hostname in ("instagram.com", "www.instagram.com"):
        if any(x in p.path for x in ("/accounts/login", "/challenge", "/checkpoint")):
            return False
        return not p.path.casefold().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".gif"))
    return approved_cdn(url) and resource_type in ("script", "stylesheet")


class PublicBrowser:
    def __init__(self, cfg, state, *, clock=time.time, page_factory=None):
        self.cfg, self.state, self.clock = cfg, state, clock
        self.page_factory = page_factory
        self.started = clock()
        self.last_status = {}

    @staticmethod
    def guard(route):
        request = route.request
        if request_allowed(request.url, request.resource_type, request.method):
            route.fallback()
        else:
            route.abort("blockedbyclient")

    @contextmanager
    def page(self):
        if self.page_factory:
            with self.page_factory(self.guard) as page:
                yield page
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SetupError("Install requirements-browser.txt and run: python -m playwright install chromium") from None
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(headless=self.cfg.browser_headless)
            except Exception:
                raise SetupError("Chromium unavailable; run: python -m playwright install chromium") from None
            try:
                context = browser.new_context(accept_downloads=False, service_workers="block")
                context.route("**/*", self.guard)
                page = context.new_page()
                page.set_default_timeout(10000)
                page.on("popup", lambda popup: popup.close())
                yield page
            finally:
                browser.close()

    def check_time(self):
        if self.clock() - self.started > self.cfg.max_runtime - 60:
            raise ProviderError("browser", "runtime_cap", stop=True, wait=300)
        until = self.state.kv_get("cooldown/browser") or 0
        if type(until) in (int, float) and until > self.clock():
            raise ProviderError("browser", "cooldown", stop=True, wait=until - self.clock())

    @staticmethod
    def check_wall(page):
        p = secure_url(page.url)
        if not p or p.hostname not in ("instagram.com", "www.instagram.com"):
            raise ProviderError("browser", "navigation_blocked", retry=False, stop=True)
        if any(x in p.path for x in ("/accounts/login", "/challenge", "/checkpoint")):
            raise ProviderError("browser", "login_or_challenge", retry=False, stop=True)
        if page.locator('input[type="password"], iframe[src*="captcha" i], [data-testid="captcha"]').count():
            raise ProviderError("browser", "login_or_challenge", retry=False, stop=True)

    def visit(self, page, url):
        self.check_time()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            # No upstream browser error/URL text (signed query strings may be present).
            raise ProviderError("browser", "navigation_unavailable", stop=True, wait=300) from None
        if response and response.status == 429:
            raise ProviderError("browser", "rate_limit", stop=True, wait=retry_after(response.headers))
        if response and response.status in (401, 403):
            raise ProviderError("browser", "access_blocked", retry=False, stop=True)
        if response and response.status >= 400:
            raise ProviderError("browser", "http_" + str(response.status), retry=response.status >= 500)
        self.check_wall(page)

    def label(self, label):
        if not label.startswith("@") or profile_handle(label[1:]) not in self.cfg.accounts:
            raise SetupError("Public browsing is restricted to your configured ACCOUNTS")
        return profile_handle(label[1:])

    def source(self, label):
        self.cfg.target.validate()
        handle = self.label(label)
        results, seen, stale = [], set(), 0
        reason = "scroll_limit"
        with self.page() as page:
            self.visit(page, "https://www.instagram.com/" + handle + "/")
            for _ in range(self.cfg.browser_scrolls):
                self.check_time()
                self.check_wall(page)
                urls = page.locator('a[href]').evaluate_all("items => items.slice(0, 5000).map(x => x.href)")
                if not isinstance(urls, list):
                    raise ProviderError("browser", "invalid_dom")
                fresh = []
                for raw in urls:
                    link = permalink(raw)
                    if not link or link in seen:
                        continue
                    seen.add(link)
                    ident = media_key(link)
                    data = {"id": ident, "media_type": "VIDEO" if "/reel/" in link else "IMAGE",
                            "permalink": link, "needs_hydration": True, "origin": "public_browser"}
                    fresh.append({"id": ident, "source": label, "data": data})
                    results.append(data)
                    if len(results) >= self.cfg.browser_posts:
                        break
                # Persist discovered links before any later navigation/scroll can fail.
                self.state.enqueue(fresh)
                if len(results) >= self.cfg.browser_posts:
                    reason = "requested_limit_reached"
                    break
                stale = 0 if fresh else stale + 1
                if stale >= 3:
                    reason = "no_more_public_links_visible"
                    break
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(self.cfg.browser_delay * 1000)
        self.last_status = {"collected": len(results), "reason": reason,
                            "coverage_complete": False, "media_downloaded": False}
        self.state.kv_set("browser/status/" + handle, self.last_status)
        return results

    def refresh(self, label, media_id):
        self.label(label)
        item = self.state.inspect(media_id)
        link = permalink((item or {}).get("data", {}).get("permalink"))
        if not link or media_key(link) != media_id:
            raise SetupError("Post was not discovered in this configured watch queue")
        with self.page() as page:
            self.visit(page, link)
            raw = page.evaluate("""() => ({
              canonical: document.querySelector('link[rel="canonical"]')?.href ||
                         document.querySelector('meta[property="og:url"]')?.content || '',
              article: !!document.querySelector('article'),
              caption: (document.querySelector('article h1')?.textContent ||
                        document.querySelector('meta[property="og:description"]')?.content || '').slice(0, 8000),
              images: [document.querySelector('meta[property="og:image"]')?.content,
                       ...Array.from(document.querySelectorAll('article img'))
                       .filter(x => !/profile (picture|photo)/i.test(x.alt || '')).map(x => x.src)].filter(Boolean).slice(0, 50),
              video: !!document.querySelector('article video') ||
                      (document.querySelector('meta[property="og:type"]')?.content || '').includes('video')
            })""")
            if not isinstance(raw, dict) or not isinstance(raw.get("caption"), str) or not isinstance(raw.get("images"), list):
                raise ProviderError("browser", "invalid_post_dom")
            # A redirected/login/profile preview must not become evidence for a post.
            if raw.get("canonical"):
                if permalink(raw["canonical"]) != link:
                    raise ProviderError("browser", "post_identity_mismatch", retry=False)
            elif raw.get("article") is not True:
                raise ProviderError("browser", "post_metadata_unavailable")
            data = {"id": media_id, "permalink": link, "origin": "public_browser", "needs_hydration": False}
            if child_safety_request(raw["caption"]):
                return {**data, "media_type": "IMAGE", "media_blocked": True}
            if self.cfg.needs_sale_context:
                data["sale_signals"] = sale_signals(raw["caption"])
            if raw.get("video") is True or "/reel/" in link:
                return {**data, "media_type": "VIDEO"}
            unique = {}
            for url in raw["images"]:
                if approved_cdn(url):
                    unique.setdefault(urlsplit(url).path, url)
            if not unique:
                return None
            children = [{"id": media_id if i == 0 else str(int(hashlib.sha256((media_id + ':' + path).encode()).hexdigest(), 16) % 10**48),
                         "media_type": "IMAGE", "media_url": url}
                        for i, (path, url) in enumerate(list(unique.items())[:self.cfg.max_children])]
            # DOM visibility cannot prove every carousel child was exposed.
            return {**data, "media_type": "CAROUSEL_ALBUM", "children": children, "children_complete": False}

    def check_access(self):
        if not self.cfg.accounts:
            raise SetupError("Configure at least one public profile")
        self.source("@" + self.cfg.accounts[0])
        return self.last_status
