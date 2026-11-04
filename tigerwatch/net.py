from __future__ import annotations

import json
import logging
import math
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from .errors import ProviderError

JSON_LIMIT = 2_000_000


def strict_json_loads(raw):
    """Reject ambiguous duplicate keys and non-finite provider/model values."""
    def object_value(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON number")
        return number

    def invalid_constant(value):
        raise ValueError("non-finite JSON constant")

    return json.loads(raw, object_pairs_hook=object_value, parse_float=finite_float,
                      parse_constant=invalid_constant)


def session():
    http = requests.Session()
    http.mount("https://", HTTPAdapter(max_retries=0))
    http.headers["User-Agent"] = "TigerWatchAI/4.0"
    return http


class Redact(logging.Filter):
    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = tuple(x for x in secrets if x)

    def filter(self, record):
        message = record.getMessage()
        for value in self.secrets:
            message = message.replace(value, "[REDACTED]")
        message = re.sub(r"(?i)(access_token|apikey|key|appsecret_proof)=([^&\s]+)", r"\1=[REDACTED]", message)
        message = re.sub(r"/bot[^/\s]+/", "/bot[REDACTED]/", message)
        record.msg, record.args = message, ()
        # Our entrypoint reports stable codes, never tracebacks containing HTTP URLs.
        record.exc_info = None
        return True


def secure_url(url):
    try:
        if not isinstance(url, str) or len(url) > 8192 or re.search(r"[\x00-\x20\x7f\\]", url):
            return None
        p = urlsplit(url)
        if p.scheme != "https" or p.username is not None or p.password is not None or p.port not in (None, 443) or p.fragment:
            return None
        if not p.hostname or not re.fullmatch(r"[a-zA-Z0-9.-]+", p.hostname) or p.hostname.endswith("."):
            return None
        return p
    except (ValueError, TypeError):
        return None


def trusted_service_url(url, suffix):
    p = secure_url(url)
    return bool(p and p.hostname.endswith("." + suffix) and p.path in ("", "/") and not p.query)


def retry_after(headers, default=300):
    raw = headers.get("Retry-After", headers.get("retry-after", ""))
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            seconds = dt.timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return default
    if not 0 <= seconds <= 86400:
        return default
    return max(1, seconds)


def read_limited(response, limit):
    length = response.headers.get("Content-Length", response.headers.get("content-length"))
    if length:
        try:
            if int(length) < 0 or int(length) > limit:
                raise ProviderError("http", "response_too_large", retry=False)
        except ValueError:
            raise ProviderError("http", "invalid_content_length", retry=False) from None
    data = bytearray()
    for block in response.iter_content(65536):
        data.extend(block)
        if len(data) > limit:
            raise ProviderError("http", "response_too_large", retry=False)
    return bytes(data)


def json_request(http, method, url, provider, *, raw_status=False, **kwargs):
    try:
        with http.request(method, url, allow_redirects=False, stream=True, **kwargs) as r:
            status, headers = r.status_code, dict(r.headers)
            raw = read_limited(r, JSON_LIMIT)
    except requests.RequestException:
        raise ProviderError(provider, "transport", stop=provider in ("supabase", "telegram"),
                            unknown=provider == "telegram") from None
    except ProviderError as exc:
        # A send may have committed even when its response cannot be read safely.
        # Keep the unknown-delivery marker instead of permitting a blind resend.
        raise ProviderError(provider, exc.code, retry=exc.retry, stop=provider in ("supabase", "telegram"),
                            unknown=provider == "telegram") from None
    try:
        body = strict_json_loads(raw)
        valid_json = True
    except (ValueError, UnicodeError, RecursionError):
        body = None
        valid_json = False
    if raw_status:
        return status, headers, body
    if status in (401, 403, 404):
        raise ProviderError(provider, f"http_{status}", retry=False, stop=True)
    if status == 429 or status >= 500:
        raise ProviderError(provider, f"http_{status}", stop=True, wait=retry_after(headers),
                            unknown=provider == "telegram" and status >= 500)
    if not 200 <= status < 300:
        raise ProviderError(provider, f"http_{status}", retry=False, stop=provider == "gemini")
    if not valid_json:
        raise ProviderError(provider, "invalid_json", unknown=provider == "telegram")
    return body
