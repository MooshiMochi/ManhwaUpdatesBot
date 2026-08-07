from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import aiohttp
import discord

from .config import NotificationsConfig

_log = logging.getLogger(__name__)
_ELIGIBLE_WEBSITES = frozenset({"comix"})
_IMAGE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class CoverAttachmentAsset:
    data: bytes
    filename: str

    @property
    def uri(self) -> str:
        return f"attachment://{self.filename}"

    def to_file(self) -> discord.File:
        return discord.File(io.BytesIO(self.data), filename=self.filename)


@dataclass(frozen=True)
class _CacheEntry:
    asset: CoverAttachmentAsset
    expires_at: float


class NotificationCoverRelay:
    def __init__(
        self,
        config: NotificationsConfig,
        *,
        session: Any | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._config = config
        self._session = session
        self._owns_session = session is None
        self._clock = clock
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._cache_bytes = 0
        self._cache_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[CoverAttachmentAsset | None]] = {}

    async def prepare(
        self, *, website_key: str, cover_url: str | None
    ) -> CoverAttachmentAsset | None:
        if not self._config.cover_attachment_enabled:
            self._fallback("disabled")
            return None
        if str(website_key or "").strip().lower() not in _ELIGIBLE_WEBSITES:
            self._fallback("ineligible_site")
            return None
        validated = self._validate_url(cover_url)
        if validated is None:
            return None

        task: asyncio.Task[CoverAttachmentAsset | None]
        async with self._cache_lock:
            self._purge_expired_cache_entries()
            cached = self._cache.get(validated)
            if cached is not None:
                self._cache.move_to_end(validated)
                _log.info(
                    "cover_relay cache_hit website=comix bytes=%s",
                    len(cached.asset.data),
                )
                return cached.asset
            task = self._inflight.get(validated)
            if task is None:
                task = asyncio.create_task(self._download_and_cache(validated))
                self._inflight[validated] = task
        try:
            return await task
        except TimeoutError:
            self._fallback("timeout")
        except aiohttp.ClientError:
            self._fallback("network")
        except Exception:
            self._fallback("network")
            _log.debug("cover_relay request failed", exc_info=True)
        finally:
            async with self._cache_lock:
                if self._inflight.get(validated) is task:
                    self._inflight.pop(validated, None)
        return None

    async def close(self) -> None:
        async with self._cache_lock:
            inflight = tuple(self._inflight.values())
            self._inflight.clear()
        for task in inflight:
            task.cancel()
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        if not self._owns_session or self._session is None:
            return
        if not bool(getattr(self._session, "closed", False)):
            await self._session.close()

    def _validate_url(self, value: str | None) -> str | None:
        if not isinstance(value, str) or not value.strip():
            self._fallback("invalid_url")
            return None
        candidate = value.strip()
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError:
            self._fallback("invalid_url")
            return None
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
        ):
            self._fallback("invalid_url")
            return None
        hosts = {host.strip().lower() for host in self._config.cover_attachment_hosts}
        if parsed.hostname.lower() not in hosts:
            self._fallback("untrusted_host")
            return None
        return candidate

    async def _download_and_cache(self, url: str) -> CoverAttachmentAsset | None:
        asset = await self._download(url)
        if asset is None:
            return None
        async with self._cache_lock:
            previous = self._cache.pop(url, None)
            if previous is not None:
                self._cache_bytes -= len(previous.asset.data)
            if len(asset.data) <= self._config.cover_attachment_cache_max_bytes:
                self._cache[url] = _CacheEntry(
                    asset=asset,
                    expires_at=(self._clock() + self._config.cover_attachment_cache_ttl_seconds),
                )
                self._cache_bytes += len(asset.data)
                while (
                    self._cache
                    and self._cache_bytes > self._config.cover_attachment_cache_max_bytes
                ):
                    _, evicted = self._cache.popitem(last=False)
                    self._cache_bytes -= len(evicted.asset.data)
        return asset

    def _purge_expired_cache_entries(self) -> None:
        now = self._clock()
        expired_urls = [url for url, entry in self._cache.items() if entry.expires_at <= now]
        for url in expired_urls:
            entry = self._cache.pop(url)
            self._cache_bytes -= len(entry.asset.data)

    async def _download(self, url: str) -> CoverAttachmentAsset | None:
        session = self._get_session()
        started = monotonic()
        async with session.get(url, allow_redirects=False) as response:
            if int(response.status) in {301, 302, 303, 307, 308}:
                self._fallback("redirect")
                return None
            if int(response.status) < 200 or int(response.status) >= 300:
                self._fallback("http")
                return None
            mime = str(response.headers.get("Content-Type") or "").partition(";")[0].lower()
            extension = _IMAGE_EXTENSIONS.get(mime)
            if extension is None:
                self._fallback("mime")
                return None
            raw_length = response.headers.get("Content-Length")
            if raw_length:
                try:
                    if int(raw_length) > self._config.cover_attachment_max_bytes:
                        self._fallback("too_large")
                        return None
                except ValueError:
                    pass
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                total += len(chunk)
                if total > self._config.cover_attachment_max_bytes:
                    self._fallback("too_large")
                    return None
                chunks.append(bytes(chunk))
        data = b"".join(chunks)
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        elapsed_ms = max(0, int((monotonic() - started) * 1000))
        _log.info(
            "cover_relay downloaded website=comix duration_ms=%s bytes=%s",
            elapsed_ms,
            len(data),
        )
        return CoverAttachmentAsset(data=data, filename=f"comix-cover-{digest}{extension}")

    def _get_session(self) -> Any:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._config.cover_attachment_timeout_seconds),
                trust_env=False,
            )
        return self._session

    @staticmethod
    def _fallback(reason: str) -> None:
        _log.info("cover_relay fallback website=comix reason=%s", reason)


__all__ = ["CoverAttachmentAsset", "NotificationCoverRelay"]
