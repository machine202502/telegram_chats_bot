"""Безопасные превью ссылок: Open Graph для сайтов и YouTube."""

from __future__ import annotations

from i18n import tr

import html as html_module
import ipaddress
import json
import re
import socket
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests

CACHE_TTL = 3600
CACHE_LIMIT = 400
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?[^#]*v=|shorts/|embed/)|youtu\.be/)([A-Za-z0-9_-]{6,})",
    re.I,
)


class PreviewError(Exception):
    pass


def _host_is_public(host: str) -> bool:
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise PreviewError(tr('backend.120')) from exc
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not address.is_global:
            raise PreviewError(tr('backend.121'))
    return True


def _validate(url: str) -> tuple[str, str]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise PreviewError(tr('backend.122'))
    if parsed.username or parsed.password:
        raise PreviewError(tr('backend.122'))
    _host_is_public(parsed.hostname)
    return parsed.geturl(), parsed.hostname


def youtube_id(url: str) -> str | None:
    match = YOUTUBE_RE.search(url)
    if match:
        return match.group(1)
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.hostname and "youtube.com" in parsed.hostname and parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v")
        if values and re.fullmatch(r"[A-Za-z0-9_-]{6,}", values[0]):
            return values[0]
    return None


def _meta_map(page: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        name_match = re.search(r"(?:property|name)\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))", tag, re.I)
        content_match = re.search(r"content\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", tag, re.I)
        if not name_match or not content_match:
            continue
        name = next((part for part in name_match.groups() if part), "").strip().lower()
        content = next((part for part in content_match.groups() if part is not None), "")
        if name and name not in result:
            result[name] = html_module.unescape(content).strip()
    return result


def _page_title(page: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", html_module.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))).strip()


def _fetch_page(url: str) -> tuple[str, str, str]:
    response = requests.get(
        url,
        headers={"User-Agent": UA, "Accept-Language": "ru,en;q=0.8"},
        timeout=(5, 7),
        stream=True,
        allow_redirects=True,
    )
    final_url = response.url
    parsed_final = urlparse(final_url)
    if parsed_final.scheme not in ("http", "https") or not parsed_final.hostname:
        response.close()
        raise PreviewError(tr('backend.123'))
    _host_is_public(parsed_final.hostname)
    ctype = (response.headers.get("Content-Type") or "").lower()
    encoding = response.encoding or "utf-8"
    if "html" not in ctype and "text/" not in ctype:
        response.close()
        return "", final_url, ctype
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(64 * 1024):
        if chunk:
            chunks.append(chunk)
            size += len(chunk)
            if size >= 512 * 1024:
                break
    response.close()
    raw = b"".join(chunks)
    try:
        page = raw.decode(encoding, errors="replace")
    except LookupError:
        page = raw.decode("utf-8", errors="replace")
    return page, final_url, ctype


def _youtube_preview(url: str, video_id: str) -> dict[str, Any]:
    title = "YouTube"
    author = ""
    thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    try:
        response = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            headers={"User-Agent": UA},
            timeout=5,
        )
        if response.ok:
            data = response.json()
            title = str(data.get("title") or title)[:180]
            author = str(data.get("author_name") or "")[:80]
            thumbnail = str(data.get("thumbnail_url") or thumbnail)
    except (requests.RequestException, ValueError):
        pass
    return {
        "type": "youtube",
        "url": url,
        "video_id": video_id,
        "title": title,
        "description": author,
        "site_name": "YouTube",
        "image": thumbnail,
    }


def fetch_preview(url: str) -> dict[str, Any]:
    original, hostname = _validate(url)
    cached = None
    with _lock:
        item = _cache.get(original)
        if item and item[0] > time.time():
            cached = item[1]
    if cached is not None:
        return cached

    video_id = youtube_id(original)
    if video_id:
        result = _youtube_preview(original, video_id)
    else:
        page, final_url, ctype = _fetch_page(original)
        metas = _meta_map(page)
        title = metas.get("og:title") or metas.get("twitter:title") or _page_title(page)
        description = (
            metas.get("og:description")
            or metas.get("twitter:description")
            or metas.get("description")
            or ""
        )
        image = metas.get("og:image") or metas.get("twitter:image") or ""
        if image:
            image = urljoin(final_url, image)
        site = metas.get("og:site_name") or hostname.replace("www.", "")
        result = {
            "type": "link",
            "url": final_url,
            "title": (title or site or hostname)[:200],
            "description": re.sub(r"\s+", " ", description).strip()[:300],
            "site_name": site[:80],
            "image": image,
        }

    with _lock:
        if len(_cache) > CACHE_LIMIT:
            oldest = sorted(_cache.items(), key=lambda pair: pair[1][0])[:50]
            for key, _value in oldest:
                _cache.pop(key, None)
        _cache[original] = (time.time() + CACHE_TTL, result)
    return result
