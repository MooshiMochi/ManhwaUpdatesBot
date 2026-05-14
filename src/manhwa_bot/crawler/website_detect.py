"""Detect the website_key for a given series URL by matching against the
supported-websites cache."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse


def series_url_from_maybe_chapter_url(url: str) -> str:
    """Best-effort conversion of common chapter URLs into series URLs."""
    raw = str(url or "").strip()
    if not raw:
        return raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return raw
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return raw

    cut_at: int | None = None
    for idx, segment in enumerate(segments):
        lowered = segment.lower()
        if lowered == "chapter" or lowered == "chapters" or lowered.startswith("chapter-"):
            cut_at = idx
            break
    if cut_at is None or cut_at == 0:
        return raw

    path = "/" + "/".join(segments[:cut_at]) + "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


async def detect_website_key(bot: Any, url: str) -> str | None:
    """Return the website_key whose ``base_url`` host matches *url*'s host.

    Reads from ``bot.websites_cache`` (populated via the crawler
    ``supported_websites`` request). Returns ``None`` when no match is found
    or the cache cannot be loaded.
    """
    if not url or "://" not in url:
        return None
    try:
        target_host = (urlparse(url).netloc or "").lower().lstrip(".")
        if target_host.startswith("www."):
            target_host = target_host[4:]
    except ValueError:
        return None
    if not target_host:
        return None

    try:
        ttl = bot.config.supported_websites_cache.ttl_seconds

        async def _loader() -> list[dict]:
            data = await bot.crawler.request("supported_websites")
            return data.get("websites") or []

        websites: list[dict] = await bot.websites_cache.get_or_set("websites_full", _loader, ttl)
    except Exception:
        return None

    for w in websites:
        base_url = w.get("base_url") or ""
        if not base_url:
            continue
        try:
            host = (urlparse(base_url).netloc or "").lower().lstrip(".")
        except ValueError:
            continue
        if host.startswith("www."):
            host = host[4:]
        if not host:
            continue
        if target_host == host or target_host.endswith("." + host):
            key = w.get("key") or w.get("website_key")
            return str(key) if key else None
    return None
