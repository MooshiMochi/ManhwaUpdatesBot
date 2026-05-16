from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from manhwa_bot.cogs.dev import DevCog


class _FakeCrawler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request(self, type_: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((type_, kwargs))
        if type_ == "supported_websites":
            return {"websites": [{"key": "asura", "base_url": "https://asura.test"}]}
        return {
            "website_key": kwargs.get("website_key"),
            "url_name": kwargs.get("url_name") or "solo-leveling",
            "title": "Solo Leveling",
            "status": "Ongoing",
            "chapter_count": 200,
            "source": "live",
        }


class _FakeCache:
    async def get_or_set(self, _key: str, loader: Any, _ttl: int) -> Any:
        return await loader()


class _FakeBot:
    def __init__(self) -> None:
        self.crawler = _FakeCrawler()
        self.websites_cache = _FakeCache()
        self.config = SimpleNamespace(supported_websites_cache=SimpleNamespace(ttl_seconds=3600))

    async def is_owner(self, _author: object) -> bool:
        return True


class _FakeContext:
    def __init__(self) -> None:
        self.author = object()
        self.sent: list[dict[str, Any]] = []

    async def send(self, *args: Any, **kwargs: Any) -> None:
        self.sent.append({"args": args, "kwargs": kwargs})


def test_dev_refetch_url_detects_website_and_forces_refresh() -> None:
    async def _run() -> None:
        bot = _FakeBot()
        ctx = _FakeContext()
        cog = DevCog(bot)  # type: ignore[arg-type]

        await DevCog.refetch.callback(cog, ctx, "https://asura.test/series/solo-leveling")

        assert bot.crawler.calls[-1] == (
            "series_data",
            {
                "website_key": "asura",
                "url": "https://asura.test/series/solo-leveling",
                "refresh": True,
                "allow_live": True,
            },
        )
        assert ctx.sent

    asyncio.run(_run())


def test_dev_refetch_chapter_url_sends_series_url() -> None:
    async def _run() -> None:
        bot = _FakeBot()
        ctx = _FakeContext()
        cog = DevCog(bot)  # type: ignore[arg-type]

        await DevCog.refetch.callback(
            cog,
            ctx,
            "https://asura.test/series/solo-leveling/chapter/200",
        )

        assert bot.crawler.calls[-1][1]["url"] == "https://asura.test/series/solo-leveling/"

    asyncio.run(_run())


def test_dev_refetch_website_key_and_url_name_forces_refresh() -> None:
    async def _run() -> None:
        bot = _FakeBot()
        ctx = _FakeContext()
        cog = DevCog(bot)  # type: ignore[arg-type]

        await DevCog.refetch.callback(cog, ctx, "asura", "solo-leveling")

        assert bot.crawler.calls == [
            (
                "series_data",
                {
                    "website_key": "asura",
                    "url_name": "solo-leveling",
                    "refresh": True,
                    "allow_live": True,
                },
            )
        ]
        assert ctx.sent

    asyncio.run(_run())
