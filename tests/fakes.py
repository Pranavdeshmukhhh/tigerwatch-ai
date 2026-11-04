import io
import json
from urllib.parse import urlsplit

import requests
from PIL import Image


class Clock:
    def __init__(self, now=1792886400.0):
        self.now = now
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


def jpeg(color="orange"):
    image = Image.new("RGB", (32, 32), color)
    out = io.BytesIO()
    image.save(out, "JPEG")
    return out.getvalue()


def post(ident="1001", **extra):
    return {"id": ident, "media_type": "IMAGE", "media_url": f"https://scontent.cdninstagram.com/{ident}.jpg",
            "permalink": f"https://www.instagram.com/p/Test{ident}/", **extra}


def decision(tiger=True, score=0.97, real=True):
    return {"real_photo": real, "targets": [{"id": "q1", "allowed": True, "match": tiger,
            "confidence": score, "support": "supported", "boxes": [[100, 100, 900, 900]] if tiger else []}]}


def gemini_response(answer):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(answer)}]}}]}


class Response:
    def __init__(self, data=None, status=200, headers=None, content=None):
        self.status_code = status
        self.headers = headers or {}
        self.content = content if content is not None else json.dumps(data).encode()
        self.closed = False
    def iter_content(self, size):
        for start in range(0, len(self.content), size):
            yield self.content[start:start + size]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.closed = True


class FakeHTTP:
    def __init__(self):
        self.calls, self.sent = [], []
        self.posts = [post()]
        self.hashtag_pages = None
        self.business_pages = None
        self.positions = {}
        self.images = {}
        self.gemini = []
        self.telegram = []
        self.meta_failure = None
        self.ai_payloads = []

    @staticmethod
    def take(value):
        if isinstance(value, list):
            return value.pop(0) if len(value) > 1 else value[0]
        return value

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        assert kwargs.get("allow_redirects") is False
        host, path = urlsplit(url).hostname, urlsplit(url).path
        if host == "graph.facebook.com":
            if self.meta_failure:
                response = self.take(self.meta_failure)
                if response is not None:
                    if isinstance(response, Exception):
                        raise response
                    return response
            params = kwargs.get("params", {})
            if path.endswith("ig_hashtag_search"):
                return Response({"data": [{"id": "555"}]})
            if path.endswith("/recent_media"):
                pages = self.hashtag_pages or [{"data": self.posts}]
                key = "hashtag"
                if not params.get("after"):
                    self.positions[key] = 0
                else:
                    self.positions[key] = self.positions.get(key, 0) + 1
                return Response(pages[min(self.positions[key], len(pages) - 1)])
            if "business_discovery" in params.get("fields", ""):
                pages = self.business_pages or [{"data": self.posts}]
                key = "business"
                if ".after(" not in params["fields"]:
                    self.positions[key] = 0
                else:
                    self.positions[key] = self.positions.get(key, 0) + 1
                return Response({"business_discovery": {"media": pages[min(self.positions[key], len(pages) - 1)]}})
            if path.endswith("me/permissions"):
                return Response({"data": [{"permission": x, "status": "granted"} for x in (
                    "instagram_basic", "instagram_manage_insights", "pages_read_engagement")]})
            return Response({"id": "123", "username": "tester"})
        if host and host.endswith("cdninstagram.com"):
            r = self.take(self.images.get(url, Response(headers={"Content-Type": "image/jpeg"}, content=jpeg())))
            if isinstance(r, Exception):
                raise r
            return r
        if host == "generativelanguage.googleapis.com":
            self.ai_payloads.append(kwargs["json"])
            r = self.take(self.gemini) if self.gemini else Response(gemini_response(decision()))
            if isinstance(r, Exception):
                raise r
            return r
        if host == "api.telegram.org":
            r = self.take(self.telegram) if self.telegram else Response({"ok": True, "result": {"message_id": len(self.sent) + 1}})
            if isinstance(r, Exception):
                raise r
            if r.status_code == 200:
                self.sent.append(kwargs)
            return r
        raise AssertionError(f"Offline fake rejects unexpected host: {host}")

    def close(self):
        pass

    def count(self, part):
        return sum(part in u for _, u, _ in self.calls)


class OfflineViolation(requests.RequestException):
    pass
