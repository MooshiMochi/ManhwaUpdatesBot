from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from manhwa_bot.cogs.catalog import CatalogCog


class _FakeResponse:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


class _FakeInteraction:
    def __init__(self) -> None:
        self.response = _FakeResponse()
        self.user = SimpleNamespace(id=123)
        self.edits: list[dict[str, Any]] = []

    async def edit_original_response(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)


class _FakeCrawler:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def request_with_progress(self, type_: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((type_, kwargs))
        return {"results": [], "failed_websites": []}


def test_search_uses_crawler_timeout_as_payload_not_ws_response_deadline() -> None:
    async def _run() -> None:
        crawler = _FakeCrawler()
        bot = SimpleNamespace(crawler=crawler, db=None)
        interaction = _FakeInteraction()
        cog = CatalogCog(bot)  # type: ignore[arg-type]

        await CatalogCog.search.callback(
            cog,
            interaction,  # type: ignore[arg-type]
            "solo",
            "aniwatch",
        )

        assert len(crawler.calls) == 1
        type_, kwargs = crawler.calls[0]
        assert type_ == "search"
        assert kwargs["query"] == "solo"
        assert kwargs["website_key"] == "aniwatch"
        assert kwargs["timeout_ms"] == 15_000
        assert "timeout" not in kwargs

    asyncio.run(_run())
