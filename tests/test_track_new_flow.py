"""Focused `/track new` orchestration tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from manhwa_bot.cogs import tracking as tracking_module
from manhwa_bot.cogs.tracking import TrackingCog


def _series_payload(*, terminal: bool) -> dict:
    if terminal:
        url_name = "teach-me-first"
        title = "Teach Me First"
        status = "Completed"
        chapter = "Chapter 20 - The End"
    else:
        url_name = "milf-exchange-plan"
        title = "MILF Exchange Plan"
        status = "Ongoing"
        chapter = "Chapter 84"
    series_url = f"https://theblank.net/serie/{url_name}/"
    return {
        "website_key": "theblank",
        "url_name": url_name,
        "series_url": series_url,
        "tracked": not terminal,
        "source": "terminal_status" if terminal else "bootstrap",
        "blocked_reason": "terminal_status" if terminal else None,
        "series": {
            "title": title,
            "cover_url": f"https://theblank.net/storage/series/covers/{url_name}.webp",
            "status": status,
            "latest_chapters": [
                {
                    "index": 84 if not terminal else 20,
                    "name": chapter,
                    "url": f"{series_url}chapter/latest",
                    "is_premium": False,
                }
            ],
        },
    }


class _Crawler:
    def __init__(self, payload: dict) -> None:
        self.connected = True
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    async def request_with_progress(self, type_: str, **fields) -> dict:
        self.calls.append((type_, fields))
        return self.payload

    async def request(self, type_: str, **fields) -> dict:
        self.calls.append((type_, fields))
        return {"new_chapters": 0}


def _interaction() -> SimpleNamespace:
    guild = SimpleNamespace(id=123)
    return SimpleNamespace(
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
        guild=guild,
        guild_id=guild.id,
    )


def _cog(payload: dict) -> tuple[TrackingCog, _Crawler]:
    crawler = _Crawler(payload)
    bot = SimpleNamespace(db=SimpleNamespace(), crawler=crawler)
    cog = TrackingCog(bot)  # type: ignore[arg-type]
    cog._tracked = SimpleNamespace(
        upsert_series=AsyncMock(),
        add_to_guild=AsyncMock(),
    )
    cog._guild_settings = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(auto_create_role=False))
    )
    cog._resolve_notifications_channel = AsyncMock(return_value=object())  # type: ignore[method-assign]
    return cog, crawler


def test_track_new_uses_seed_result_without_immediate_check(
    monkeypatch,
) -> None:
    payload = _series_payload(terminal=False)
    cog, crawler = _cog(payload)
    interaction = _interaction()
    success_view = object()
    success_builder = Mock(return_value=success_view)
    monkeypatch.setattr(
        tracking_module,
        "_resolve_track_input",
        AsyncMock(return_value=("theblank", payload["series_url"])),
    )
    monkeypatch.setattr(tracking_module, "build_tracking_success_view", success_builder)

    async def _run() -> None:
        await TrackingCog.track_new.callback(cog, interaction, payload["series_url"], None)

    asyncio.run(_run())

    assert [type_ for type_, _ in crawler.calls] == ["track_series"]
    cog._tracked.upsert_series.assert_awaited_once()
    cog._tracked.add_to_guild.assert_awaited_once_with(
        123,
        "theblank",
        "milf-exchange-plan",
        None,
    )
    assert success_builder.call_args.kwargs["title"] == "MILF Exchange Plan"
    assert success_builder.call_args.kwargs["cover_url"].endswith("milf-exchange-plan.webp")
    assert success_builder.call_args.kwargs["warning"] is None
    assert interaction.edit_original_response.await_args.kwargs["view"] is success_view


def test_track_new_terminal_result_uses_full_metadata_without_followup_check(
    monkeypatch,
) -> None:
    payload = _series_payload(terminal=True)
    cog, crawler = _cog(payload)
    interaction = _interaction()
    blocked_view = object()
    blocked_builder = Mock(return_value=blocked_view)
    monkeypatch.setattr(
        tracking_module,
        "_resolve_track_input",
        AsyncMock(return_value=("theblank", payload["series_url"])),
    )
    monkeypatch.setattr(
        tracking_module,
        "build_terminal_tracking_blocked_view",
        blocked_builder,
    )

    async def _run() -> None:
        await TrackingCog.track_new.callback(cog, interaction, payload["series_url"], None)

    asyncio.run(_run())

    assert [type_ for type_, _ in crawler.calls] == ["track_series"]
    cog._tracked.upsert_series.assert_awaited_once()
    cog._tracked.add_to_guild.assert_not_awaited()
    assert blocked_builder.call_args.kwargs["title"] == "Teach Me First"
    assert blocked_builder.call_args.kwargs["status"] == "Completed"
    assert blocked_builder.call_args.kwargs["cover_url"].endswith("teach-me-first.webp")
    assert interaction.edit_original_response.await_args.kwargs["view"] is blocked_view


def test_track_new_preserves_auto_role_warning(monkeypatch) -> None:
    payload = _series_payload(terminal=False)
    cog, _ = _cog(payload)
    interaction = _interaction()
    success_builder = Mock(return_value=object())
    cog._guild_settings.get = AsyncMock(return_value=SimpleNamespace(auto_create_role=True))
    cog._auto_create_ping_role = AsyncMock(return_value=None)  # type: ignore[method-assign]
    monkeypatch.setattr(
        tracking_module,
        "_resolve_track_input",
        AsyncMock(return_value=("theblank", payload["series_url"])),
    )
    monkeypatch.setattr(tracking_module, "build_tracking_success_view", success_builder)

    async def _run() -> None:
        await TrackingCog.track_new.callback(cog, interaction, payload["series_url"], None)

    asyncio.run(_run())

    warning = success_builder.call_args.kwargs["warning"]
    assert "Auto-Create Role is on" in warning
    assert "immediate update check failed" not in warning
