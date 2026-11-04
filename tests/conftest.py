from dataclasses import replace
from functools import partial

import pytest
import requests

from tigerwatch.config import Config
from tigerwatch.media import download_image
from tigerwatch.meta import Meta
from tigerwatch.store import State
from tigerwatch.worker import Worker
from .fakes import Clock, FakeHTTP


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Real HTTP is blocked in the offline test suite")
    monkeypatch.setattr(requests.sessions.Session, "request", reject)
    for key, value in {"META_ACCESS_TOKEN": "meta-secret", "IG_USER_ID": "123", "GEMINI_API_KEY": "gemini-secret",
                       "TELEGRAM_BOT_TOKEN": "telegram-secret", "TELEGRAM_CHAT_ID": "5",
                       "FREE_PLANS_CONFIRMED": "true", "GITHUB_ACTIONS": "false",
                       "SUPABASE_URL": "", "SUPABASE_SERVICE_ROLE_KEY": ""}.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def pipeline(tmp_path):
    clock, http = Clock(), FakeHTTP()
    cfg = replace(Config(), free_plans_confirmed=True, tags=("tiger",), sqlite_path=str(tmp_path / "test.sqlite3"))
    state = State(cfg, http, clock=clock)
    class Pipeline:
        def __init__(self):
            self.cfg, self.clock, self.http, self.state = cfg, clock, http, state
        def run(self, discover=True):
            self.state.cfg = self.cfg
            meta = Meta(self.cfg, self.http, self.state, clock=self.clock, sleep=self.clock.sleep)
            self.worker = Worker(self.cfg, self.state, meta, self.http, clock=self.clock, sleep=self.clock.sleep,
                                 downloader=partial(download_image, resolve=lambda host: None))
            return self.worker.run(discover=discover)
    p = Pipeline()
    yield p
    state.close()
