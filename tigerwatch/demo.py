"""Offline demo. The synthetic orange square is NOT a tiger accuracy test."""
import io
import json
import tempfile
from dataclasses import replace

from PIL import Image

from .config import Config
from .store import State
from .worker import Worker


def run_demo():
    class HTTP:
        def request(self, method, url, **kwargs):
            from contextlib import nullcontext
            if "generativelanguage.googleapis.com" in url:
                data = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(
                    {"real_photo": True, "targets": [{"id": "q1", "allowed": True, "match": True,
                      "confidence": 0.96, "support": "supported", "boxes": [[100, 100, 900, 900]]}]})}]}}]}
            elif "api.telegram.org" in url:
                data = {"ok": True, "result": {"message_id": 1}}
            else:
                raise AssertionError("Offline demo blocks every other URL")
            class Response:
                status_code, headers = 200, {}
                def iter_content(self, size):
                    yield json.dumps(data).encode()
            return nullcontext(Response())
    class Meta:
        def refresh(self, source, ident):
            return None
    from unittest.mock import patch
    with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {
        "GEMINI_API_KEY": "demo", "TELEGRAM_BOT_TOKEN": "demo", "TELEGRAM_CHAT_ID": "demo", "SUPABASE_SERVICE_ROLE_KEY": ""}):
        cfg = replace(Config(), free_plans_confirmed=True, tags=("tiger",), sqlite_path=tmp + "/demo.sqlite3")
        http = HTTP()
        state = State(cfg, http)
        image = Image.new("RGB", (20, 20), "orange")
        dest = io.BytesIO()
        image.save(dest, "JPEG")
        state.enqueue([{"id": "1001", "source": "#tiger", "data": {"id": "1001", "media_type": "IMAGE",
            "media_url": "https://demo.cdninstagram.com/sample.jpg", "permalink": "https://www.instagram.com/p/DEMO/"}}])
        Worker(cfg, state, Meta(), http, downloader=lambda *a: dest.getvalue()).run(discover=False)
        print("SIMULATED: synthetic pixels, mocked Gemini and Telegram; no network or wildlife accuracy verification.")
        print(json.dumps(state.stats(), indent=2))
        state.close()
