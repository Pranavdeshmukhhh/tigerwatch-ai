"""Asset safety and accessibility contracts for the local-only glass interface."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest

from tigerwatch.dashboard_assets import HTML, CSS, JS


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs), tuple(self.stack)))
        if tag not in {'input', 'meta', 'link', 'br'}:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack.pop() != tag:
                pass


def parsed():
    page = Page()
    page.feed(HTML)
    return page.tags


def test_assets_work_under_strict_same_origin_csp():
    tags = parsed()
    assert [(a.get('src')) for t, a, _ in tags if t == 'script'] == ['/app.js']
    assert [(a.get('href')) for t, a, _ in tags if t == 'link'] == ['/style.css']
    assert not any(t in {'img', 'iframe', 'video', 'audio', 'object', 'embed'} for t, _, _ in tags)
    for _, attrs, _ in tags:
        assert not any(k == 'style' or k.startswith('on') for k in attrs)
        for key in ('src', 'href', 'action'):
            if key in attrs:
                assert attrs[key].startswith(('/', '#')) and not attrs[key].startswith('//')
    assert 'url(' not in CSS.lower()  # CSS gradients, never remote image/font loads.


def test_control_labels_and_landmarks_are_available_without_visual_cues():
    tags = parsed()
    ids = [a['id'] for _, a, _ in tags if 'id' in a]
    assert len(ids) == len(set(ids))
    labels = {a['for'] for t, a, _ in tags if t == 'label' and 'for' in a}
    for tag, attrs, parents in tags:
        if tag in {'input', 'textarea', 'select'}:
            assert attrs.get('id') in labels or 'label' in parents
    assert any(t == 'nav' and a.get('aria-label') for t, a, _ in tags)
    assert any(t == 'main' for t, _, _ in tags)
    assert any(a.get('role') == 'status' and a.get('aria-live') == 'polite' for _, a, _ in tags)
    assert any(t == 'a' and a.get('href') == '#overview' and a.get('class') == 'skip-link' for t, a, _ in tags)


def test_private_client_avoids_persistent_credentials_and_html_execution_sinks():
    for forbidden in ('localStorage', 'sessionStorage', 'document.cookie', '.innerHTML', '.outerHTML', 'insertAdjacentHTML', 'eval(', 'new Function('):
        assert forbidden not in JS
    assert 'prefers-reduced-motion:reduce' in CSS
    assert 'prefers-reduced-transparency:reduce' in CSS
    assert 'forced-colors:active' in CSS
    assert 'prefers-color-scheme:dark' in CSS


def test_javascript_parses_as_a_standalone_same_origin_asset(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node syntax checker unavailable; Chromium integration checks JS separately')
    path = Path(tmp_path) / 'dashboard.js'
    path.write_text(JS)
    result = subprocess.run([node, '--check', str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
