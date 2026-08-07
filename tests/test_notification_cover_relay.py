from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest

from manhwa_bot.config import NotificationsConfig
from manhwa_bot.notification_cover_relay import NotificationCoverRelay

_JPEG = b"\xff\xd8\xff\xe0" + b"cover-bytes"


def _config(**overrides: Any) -> NotificationsConfig:
    base = NotificationsConfig(
        fanout_concurrency=8,
        dm_fanout_concurrency=4,
        respect_paid_chapter_setting=True,
    )
    return replace(base, **overrides)


class _Content:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class _BlockingContent(_Content):
    def __init__(self, started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__([_JPEG])
        self._started = started
        self._release = release

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        self._started.set()
        await self._release.wait()
        yield _JPEG


class _Response:
    def __init__(
        self,
        *,
        status: int = 200,
        content_type: str = "image/jpeg",
        chunks: list[bytes] | None = None,
        content_length: int | None = None,
        content: _Content | None = None,
    ) -> None:
        self.status = status
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.content = content or _Content(chunks or [_JPEG])

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def __init__(self, responses: list[_Response] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[tuple[str, bool]] = []
        self.closed = False

    def get(self, url: str, *, allow_redirects: bool) -> _Response:
        self.requests.append((url, allow_redirects))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("website_key", "url"),
    [
        ("comick", "https://i.ibb.co/abc/cover.jpg"),
        ("comix", "http://i.ibb.co/abc/cover.jpg"),
        ("comix", "https://evil.example/cover.jpg"),
        ("comix", "https://i.ibb.co.evil.example/cover.jpg"),
        ("comix", "https://user:pass@i.ibb.co/cover.jpg"),
        ("comix", "https://i.ibb.co:444/cover.jpg"),
    ],
)
def test_prepare_rejects_ineligible_sources_without_requesting(website_key: str, url: str) -> None:
    async def _run() -> None:
        session = _Session()
        relay = NotificationCoverRelay(_config(), session=session)

        asset = await relay.prepare(website_key=website_key, cover_url=url)

        assert asset is None
        assert session.requests == []

    asyncio.run(_run())


def test_prepare_downloads_eligible_image_without_redirects() -> None:
    async def _run() -> None:
        session = _Session([_Response()])
        relay = NotificationCoverRelay(_config(), session=session)

        asset = await relay.prepare(website_key="comix", cover_url="https://i.ibb.co/abc/cover.jpg")

        assert asset is not None
        assert asset.data == _JPEG
        assert asset.filename.startswith("comix-cover-")
        assert asset.filename.endswith(".jpg")
        assert asset.uri == f"attachment://{asset.filename}"
        assert session.requests == [("https://i.ibb.co/abc/cover.jpg", False)]
        first_file = asset.to_file()
        second_file = asset.to_file()
        try:
            assert first_file is not second_file
            assert first_file.uri == asset.uri
            assert second_file.uri == asset.uri
        finally:
            first_file.close()
            second_file.close()

    asyncio.run(_run())


@pytest.mark.parametrize(
    "response",
    [
        _Response(status=302),
        _Response(content_type="text/html"),
        _Response(content_length=2 * 1024 * 1024 + 1),
        _Response(chunks=[b"a" * (1024 * 1024), b"b" * (1024 * 1024 + 1)]),
    ],
)
def test_prepare_rejects_redirect_non_image_and_oversize_responses(response: _Response) -> None:
    async def _run() -> None:
        session = _Session([response])
        relay = NotificationCoverRelay(_config(), session=session)

        asset = await relay.prepare(website_key="comix", cover_url="https://i.ibb.co/abc/cover.jpg")

        assert asset is None

    asyncio.run(_run())


def test_prepare_disabled_never_requests_cover() -> None:
    async def _run() -> None:
        session = _Session()
        relay = NotificationCoverRelay(_config(cover_attachment_enabled=False), session=session)

        asset = await relay.prepare(website_key="comix", cover_url="https://i.ibb.co/abc/cover.jpg")

        assert asset is None
        assert session.requests == []

    asyncio.run(_run())


def test_prepare_caches_the_full_url_until_ttl_expires(caplog) -> None:
    caplog.set_level(logging.INFO, logger="manhwa_bot.notification_cover_relay")

    async def _run() -> None:
        now = [100.0]
        session = _Session([_Response(), _Response()])
        relay = NotificationCoverRelay(_config(), session=session, clock=lambda: now[0])
        url = "https://i.ibb.co/abc/cover.jpg"

        first = await relay.prepare(website_key="comix", cover_url=url)
        second = await relay.prepare(website_key="comix", cover_url=url)
        now[0] += 6 * 60 * 60 + 1
        third = await relay.prepare(website_key="comix", cover_url=url)

        assert first is second
        assert third is not first
        assert len(session.requests) == 2

    asyncio.run(_run())
    assert any(
        f"cover_relay cache_hit website=comix bytes={len(_JPEG)}" in record.getMessage()
        for record in caplog.records
    )


def test_prepare_shares_one_inflight_download_for_the_same_url() -> None:
    async def _run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        session = _Session([_Response(content=_BlockingContent(started=started, release=release))])
        relay = NotificationCoverRelay(_config(), session=session)
        url = "https://i.ibb.co/abc/cover.jpg"

        first_task = asyncio.create_task(relay.prepare(website_key="comix", cover_url=url))
        await started.wait()
        second_task = asyncio.create_task(relay.prepare(website_key="comix", cover_url=url))
        await asyncio.sleep(0)
        release.set()
        first, second = await asyncio.gather(first_task, second_task)

        assert first is second
        assert len(session.requests) == 1

    asyncio.run(_run())


def test_prepare_evicts_least_recently_used_entries_to_byte_limit() -> None:
    async def _run() -> None:
        session = _Session([_Response(), _Response(), _Response(), _Response()])
        relay = NotificationCoverRelay(
            _config(cover_attachment_cache_max_bytes=len(_JPEG) * 2), session=session
        )
        urls = [f"https://i.ibb.co/abc/{name}.jpg" for name in ("a", "b", "c")]

        await relay.prepare(website_key="comix", cover_url=urls[0])
        await relay.prepare(website_key="comix", cover_url=urls[1])
        await relay.prepare(website_key="comix", cover_url=urls[0])
        await relay.prepare(website_key="comix", cover_url=urls[2])
        await relay.prepare(website_key="comix", cover_url=urls[1])

        assert [request[0] for request in session.requests] == [
            urls[0],
            urls[1],
            urls[2],
            urls[1],
        ]

    asyncio.run(_run())


def test_owned_session_disables_environment_proxies_and_closes() -> None:
    async def _run() -> None:
        relay = NotificationCoverRelay(_config())
        session = relay._get_session()
        assert session.trust_env is False

        await relay.close()
        await relay.close()

        assert session.closed is True

    asyncio.run(_run())


def test_prepare_keeps_downloaded_bytes_in_memory(monkeypatch) -> None:
    async def _run() -> None:
        def _unexpected_write(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("cover relay wrote to disk")

        monkeypatch.setattr("pathlib.Path.write_bytes", _unexpected_write)
        monkeypatch.setattr("tempfile.NamedTemporaryFile", _unexpected_write)
        session = _Session([_Response()])
        relay = NotificationCoverRelay(_config(), session=session)

        asset = await relay.prepare(website_key="comix", cover_url="https://i.ibb.co/abc/cover.jpg")

        assert asset is not None
        assert asset.data == _JPEG

    asyncio.run(_run())
