from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from manhwa_bot.cogs.bookmarks import BookmarksCog
from manhwa_bot.cogs.catalog import CatalogCog
from manhwa_bot.crawler.errors import CrawlerError
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool
from manhwa_bot.db.tracked import TrackedStore


class _Cache:
    async def get_or_set(self, key, loader, ttl):
        del key, loader, ttl
        return [{"key": "toongod", "base_url": "https://www.toongod.org"}]


class _Crawler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.info_chapters: list[dict] = [
            {
                "url": "https://www.toongod.org/webtoon/someone-stop-her-uncensored/chapter-54",
                "text": "Chapter 54",
            }
        ]
        self.chapters_result: list[dict] | None = None

    async def request(self, type_: str, **kwargs) -> dict:
        self.calls.append((type_, kwargs))
        if type_ == "info":
            return {
                "website_key": "toongod",
                "url_name": "someone-stop-her-uncensored",
                "url": "https://www.toongod.org/webtoon/someone-stop-her-uncensored",
                "title": "Someone Stop Her",
                "cover_url": "https://www.toongod.org/cover.jpg",
                "status": "Ongoing",
                "chapters": self.info_chapters,
            }
        if type_ == "chapters":
            if self.chapters_result is not None:
                return {"chapters": self.chapters_result}
            raise CrawlerError("not_found", "series not found")
        raise AssertionError(type_)


async def _bot(tmp: str) -> tuple[SimpleNamespace, DbPool, _Crawler]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    crawler = _Crawler()
    bot = SimpleNamespace(
        db=pool,
        crawler=crawler,
        websites_cache=_Cache(),
        config=SimpleNamespace(supported_websites_cache=SimpleNamespace(ttl_seconds=60)),
    )
    return bot, pool, crawler


def test_bookmark_url_resolution_accepts_chapter_url_and_caches_metadata() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bot, pool, crawler = await _bot(tmp)
            try:
                cog = BookmarksCog(bot)  # type: ignore[arg-type]
                resolved = await cog._resolve_series(
                    "https://www.toongod.org/webtoon/someone-stop-her-uncensored/chapter-54/"
                )
                assert resolved is not None
                assert resolved.website_key == "toongod"
                assert resolved.url_name == "someone-stop-her-uncensored"
                assert crawler.calls[0] == (
                    "info",
                    {
                        "website_key": "toongod",
                        "url": "https://www.toongod.org/webtoon/someone-stop-her-uncensored/",
                    },
                )
                chapters = await cog._fetch_chapters_for(resolved)
                title, cover_url, status = await cog._cache_series_metadata(resolved, chapters)

                assert title == "Someone Stop Her"
                assert cover_url == "https://www.toongod.org/cover.jpg"
                assert status == "Ongoing"
                stored = await TrackedStore(pool).find("toongod", "someone-stop-her-uncensored")
                assert stored is not None
                assert stored.series_url == (
                    "https://www.toongod.org/webtoon/someone-stop-her-uncensored"
                )
                assert stored.last_chapter_text == "Chapter 54"
            finally:
                await pool.close()

    asyncio.run(_run())


def test_catalog_info_uses_live_info_chapters_when_cache_misses() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bot, pool, crawler = await _bot(tmp)
            try:
                cog = CatalogCog(bot)  # type: ignore[arg-type]
                info, chapters = await cog._fetch_info_and_chapters(
                    website_key="toongod",
                    identifier="https://www.toongod.org/webtoon/someone-stop-her-uncensored/chapter-54/",
                )

                assert info["title"] == "Someone Stop Her"
                assert [chapter["text"] for chapter in chapters] == ["Chapter 54"]
                assert [call[0] for call in crawler.calls] == ["info", "chapters"]
            finally:
                await pool.close()

    asyncio.run(_run())


def test_catalog_prefers_dedicated_chapters_when_info_chapters_lack_urls() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bot, pool, crawler = await _bot(tmp)
            try:
                crawler.info_chapters = [{"text": "Chapter 54"}]
                crawler.chapters_result = [
                    {
                        "text": "Chapter 54",
                        "url": "https://www.toongod.org/webtoon/someone-stop-her-uncensored/chapter-54",
                    }
                ]
                cog = CatalogCog(bot)  # type: ignore[arg-type]

                info, chapters = await cog._fetch_info_and_chapters(
                    website_key="toongod",
                    identifier="https://www.toongod.org/webtoon/someone-stop-her-uncensored/",
                )

                assert info["chapters"] == [{"text": "Chapter 54"}]
                assert chapters == crawler.chapters_result
                assert [call[0] for call in crawler.calls] == ["info", "chapters"]
            finally:
                await pool.close()

    asyncio.run(_run())


def test_catalog_resolves_raw_chapter_url_to_series_url_before_crawler_calls() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bot, pool, _crawler = await _bot(tmp)
            try:
                cog = CatalogCog(bot)  # type: ignore[arg-type]

                resolved = await cog._resolve_series_input(
                    "https://www.toongod.org/webtoon/someone-stop-her-uncensored/chapter-54/"
                )

                assert resolved == (
                    "toongod",
                    "https://www.toongod.org/webtoon/someone-stop-her-uncensored/",
                )
            finally:
                await pool.close()

    asyncio.run(_run())
