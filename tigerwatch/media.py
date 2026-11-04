from __future__ import annotations

import io
import ipaddress
import socket
import warnings
from urllib.parse import urljoin, urlunsplit

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import ExpiredMedia, ProviderError, UnsafeMedia
from .net import read_limited, retry_after, secure_url

IMAGE_LIMIT = 8_000_000
PIXEL_LIMIT = 20_000_000
Image.MAX_IMAGE_PIXELS = PIXEL_LIMIT
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def approved_cdn(url):
    p = secure_url(url)
    return bool(p and any(p.hostname == x or p.hostname.endswith("." + x) for x in ("fbcdn.net", "cdninstagram.com")))


def permalink(url):
    import re
    p = secure_url(url)
    if not p or p.hostname not in ("instagram.com", "www.instagram.com") or not re.fullmatch(r"/(p|reel|tv)/[a-zA-Z0-9_-]{1,100}/?", p.path):
        return None
    # Strip tracking parameters; never publish captions, EXIF or API CDN URLs.
    return urlunsplit(("https", "www.instagram.com", p.path.rstrip("/") + "/", "", ""))


def public_dns(host):
    try:
        ips = [x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    except OSError:
        raise ProviderError("cdn", "dns") from None
    if not ips or any(not ipaddress.ip_address(x).is_global for x in ips):
        raise UnsafeMedia("cdn:non_public_address")


def normalize(raw, expected_format=None):
    if len(raw) > IMAGE_LIMIT:
        raise UnsafeMedia("image:byte_limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=("JPEG", "PNG", "WEBP")) as image:
                if image.format not in FORMATS.values() or (expected_format and image.format != expected_format):
                    raise UnsafeMedia("image:format_mismatch")
                if image.width * image.height > PIXEL_LIMIT or getattr(image, "is_animated", False):
                    raise UnsafeMedia("image:pixel_limit_or_animation")
                image.load()
                image = ImageOps.exif_transpose(image)
                image.thumbnail((900, 900))
                image = image.convert("RGB")
                out = io.BytesIO()
                # A fresh image has no EXIF, GPS, comments or original metadata.
                clean = Image.new("RGB", image.size)
                clean.paste(image)
                clean.save(out, format="JPEG", quality=82, optimize=True)
                return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise UnsafeMedia("image:invalid_or_unsafe") from None


def download_image(http, url, *, resolve=public_dns):
    for _ in range(4):
        if not approved_cdn(url):
            raise UnsafeMedia("cdn:unapproved_url")
        resolve(secure_url(url).hostname)
        try:
            with http.request("GET", url, stream=True, allow_redirects=False, timeout=(8, 25)) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    target = r.headers.get("Location", r.headers.get("location", ""))
                    if not target:
                        raise UnsafeMedia("cdn:redirect_without_location")
                    url = urljoin(url, target)
                    continue
                if r.status_code in (401, 403, 404, 410):
                    raise ExpiredMedia()
                if r.status_code == 429 or r.status_code >= 500:
                    raise ProviderError("cdn", f"http_{r.status_code}", wait=retry_after(r.headers))
                if r.status_code != 200:
                    raise UnsafeMedia("cdn:unexpected_status")
                mime = r.headers.get("Content-Type", r.headers.get("content-type", "")).split(";", 1)[0].strip().lower()
                if mime not in FORMATS:
                    raise UnsafeMedia("cdn:unsupported_mime")
                try:
                    raw = read_limited(r, IMAGE_LIMIT)
                except ProviderError:
                    raise UnsafeMedia("cdn:invalid_size") from None
        except requests.RequestException:
            raise ProviderError("cdn", "transport") from None
        return normalize(raw, FORMATS[mime])
    raise UnsafeMedia("cdn:redirect_limit")
