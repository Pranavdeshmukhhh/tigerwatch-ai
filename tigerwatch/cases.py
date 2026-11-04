"""Private, local URL-only reference book. Never fetches or submits a URL."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path

from .errors import SetupError
from .media import permalink
from .net import secure_url

REPORTING = {
    "instagram": "https://help.instagram.com/",
    "ncmec": "https://www.missingkids.org/gethelpnow/cybertipline",
    "national_hotline_directory": "https://inhope.org/",
}
CATEGORIES = ("child_safety", "wildlife", "other")
STATUSES = ("needs_review", "reported", "dismissed")


def reference_url(url):
    link = permalink(url)
    if link:
        return link
    parsed = secure_url(url)
    if parsed and parsed.hostname in ("instagram.com", "www.instagram.com") and re.fullmatch(r"/[A-Za-z0-9._]{1,30}/?", parsed.path):
        handle = parsed.path.strip("/")
        if handle.casefold() not in {"accounts", "challenge", "checkpoint", "direct", "explore", "p", "reel", "reels"}:
            return "https://www.instagram.com/" + handle + "/"
    raise SetupError("Use a canonical HTTPS Instagram profile/post/reel reference, without credentials or unusual ports")


def private_json(path, value):
    path = Path(path)
    if path.is_symlink():
        raise SetupError("Refusing to overwrite a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".visualwatch-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=True, indent=2, allow_nan=False)
            f.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CaseBook:
    def __init__(self, path, *, clock=time.time):
        path = Path(path)
        if path.is_symlink():
            raise SetupError("Refusing a symlink case database")
        self.db = sqlite3.connect(path, timeout=20)
        os.chmod(path, 0o600)
        self.clock = clock
        self.db.execute("""CREATE TABLE IF NOT EXISTS visualwatch_cases(
            id TEXT PRIMARY KEY,category TEXT NOT NULL,url TEXT NOT NULL,
            status TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL)""")
        self.db.commit()

    def add(self, url, category):
        if category not in CATEGORIES:
            raise SetupError("Unknown reference category")
        link = reference_url(url)
        ident = "case-" + hashlib.sha256((category + "\n" + link).encode()).hexdigest()[:24]
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO visualwatch_cases VALUES(?,?,?,'needs_review',?,?)",
                            (ident, category, link, self.clock(), self.clock()))
        return ident

    def entries(self, *, include_urls=False):
        rows = self.db.execute("SELECT id,category,status,created,updated" + (",url" if include_urls else "") +
                               " FROM visualwatch_cases ORDER BY created DESC LIMIT 1000")
        return [dict(zip([x[0] for x in rows.description], row)) for row in rows]

    def update(self, ident, status):
        if status not in STATUSES or not re.fullmatch(r"case-[a-f0-9]{24}", ident):
            raise SetupError("Invalid case ID or review status")
        with self.db:
            return self.db.execute("UPDATE visualwatch_cases SET status=?,updated=? WHERE id=?", (status, self.clock(), ident)).rowcount == 1

    def export(self, path):
        private_json(path, {"kind": "unverified_references_only", "submitted_to_authorities": False,
                            "cases": self.entries(include_urls=True), "reporting_resources": REPORTING})

    def close(self):
        self.db.close()
