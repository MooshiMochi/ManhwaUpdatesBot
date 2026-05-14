"""Tests for tracking command crawler progress responses."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from manhwa_bot.cogs.tracking import TrackingCog
from manhwa_bot.crawler.errors import CrawlerError


class _FakeResponse:
    def __init__(self) -> None:
        self.deferred: list[dict] = []

    async def defer(self, **kwargs) -> None:
        self.deferred.append(kwargs)


class _FakeFollowup:
    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def send(self, **kwargs) -> None:
        self.sends.append(kwargs)


class _FakeInteraction:
    def __init__(self) -> None:
        self.response = _FakeResponse()
        self.followup = _FakeFollowup()
        self.user = SimpleNamespace(id=123)
        self.guild = None
        self.guild_id = None
        self.original_edits: list[dict] = []

    async def edit_original_response(self, **kwargs) -> None:
        self.original_edits.append(kwargs)


class _TerminalEditFailingInteraction(_FakeInteraction):
    async def edit_original_response(self, **kwargs) -> None:
        embed = kwargs.get("embed")
        if embed is not None and embed.title != "Running /track new":
            raise RuntimeError("discord edit rejected")
        await super().edit_original_response(**kwargs)


class _FakeChannel:
    mention = "#updates"


class _FakeGuild:
    id = 456

    def __init__(self) -> None:
        self.channel = _FakeChannel()

    def get_channel(self, channel_id: int):
        if channel_id == 789:
            return self.channel
        return None


class _FakeGuildSettings:
    async def list_scanlator_channels(self, _guild_id: int):
        return []

    async def get(self, _guild_id: int):
        return SimpleNamespace(notifications_channel_id=789)


class _FakeTrackedStore:
    def __init__(self) -> None:
        self.upserts: list[tuple] = []
        self.guild_adds: list[tuple] = []

    async def upsert_series(self, *args, **kwargs) -> None:
        self.upserts.append((args, kwargs))

    async def add_to_guild(self, *args, **kwargs) -> None:
        self.guild_adds.append((args, kwargs))


class _FailingTrackedStore(_FakeTrackedStore):
    async def upsert_series(self, *args, **kwargs) -> None:
        raise RuntimeError("database unavailable")


class _SuccessfulTrackCrawler:
    async def request_with_progress(self, type_, *, request_id, on_progress, **kwargs):
        assert type_ == "track_series"
        assert request_id
        assert kwargs == {
            "website_key": "asura",
            "series_url": "https://asurascans.example/series/solo-leveling",
        }
        await on_progress(
            SimpleNamespace(
                title="Fetching series",
                detail="Reading latest chapters",
                status="running",
            )
        )
        return {
            "website_key": "asura",
            "url_name": "solo-leveling",
            "series_url": "https://asurascans.example/series/solo-leveling",
            "series": {
                "title": "Solo Leveling",
                "status": "Ongoing",
                "cover_url": "https://asurascans.example/cover.jpg",
                "latest_chapters": [
                    {
                        "name": "Chapter 1",
                        "url": "https://asurascans.example/chapter/1",
                    }
                ],
            },
        }


class _FailingTrackCrawler:
    async def request_with_progress(self, type_, *, request_id, on_progress, **kwargs):
        assert type_ == "track_series"
        assert request_id
        assert kwargs == {
            "website_key": "asura",
            "series_url": "https://asurascans.example/series/solo-leveling",
        }
        await on_progress(
            SimpleNamespace(
                title="Fetching series",
                detail="Reading latest chapters",
                status="running",
            )
        )
        raise CrawlerError(
            code="tracking_seed_failed",
            message="seed failed",
            request_id=request_id,
        )


class _FakeBot:
    def __init__(self, crawler=None) -> None:
        self.crawler = crawler or _SuccessfulTrackCrawler()
        self.db = object()
        self.user = None


def test_track_new_edits_original_response_with_progress_then_final_success_embed() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = TrackingCog(_FakeBot())
        tracked = _FakeTrackedStore()
        cog._tracked = tracked  # type: ignore[method-assign]

        await TrackingCog.track_new.callback(  # type: ignore[attr-defined]
            cog,
            interaction,
            "asura|https://asurascans.example/series/solo-leveling",
        )

        assert interaction.response.deferred == [{"ephemeral": True}]
        assert interaction.followup.sends == []

        first_embed = interaction.original_edits[0]["embed"]
        assert first_embed.title == "Running /track new"
        assert "Sent request to crawler" in (first_embed.description or "")

        progress_embed = interaction.original_edits[1]["embed"]
        assert progress_embed.title == "Running /track new"
        assert "Fetching series: Reading latest chapters" in (progress_embed.description or "")

        final_edit = interaction.original_edits[-1]
        assert final_edit["embed"].title == "Tracking Successful"
        assert tracked.upserts
        assert tracked.guild_adds

    asyncio.run(_run())


def test_track_new_guild_context_uses_original_response_for_final_success_embed() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        interaction.guild = _FakeGuild()
        interaction.guild_id = interaction.guild.id
        cog = TrackingCog(_FakeBot())
        tracked = _FakeTrackedStore()
        cog._tracked = tracked  # type: ignore[method-assign]
        cog._guild_settings = _FakeGuildSettings()  # type: ignore[method-assign]

        await TrackingCog.track_new.callback(  # type: ignore[attr-defined]
            cog,
            interaction,
            "asura|https://asurascans.example/series/solo-leveling",
        )

        assert interaction.followup.sends == []
        final_edit = interaction.original_edits[-1]
        assert final_edit["embed"].title == "Tracking Successful"
        assert "#updates" in (final_edit["embed"].description or "")
        assert tracked.guild_adds[0][0][0] == 456

    asyncio.run(_run())


def test_track_new_post_crawler_failure_edits_original_response_with_error() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = TrackingCog(_FakeBot())
        cog._tracked = _FailingTrackedStore()  # type: ignore[method-assign]

        await TrackingCog.track_new.callback(  # type: ignore[attr-defined]
            cog,
            interaction,
            "asura|https://asurascans.example/series/solo-leveling",
        )

        assert interaction.followup.sends == []
        final_embed = interaction.original_edits[-1]["embed"]
        assert final_embed.title == "Bot Error"
        assert "database unavailable" in (final_embed.description or "")
        assert "Sent request to crawler" in (final_embed.description or "")
        assert "Fetching series: Reading latest chapters" in (final_embed.description or "")

    asyncio.run(_run())


def test_track_new_final_success_edit_failure_does_not_send_followup() -> None:
    async def _run() -> None:
        interaction = _TerminalEditFailingInteraction()
        cog = TrackingCog(_FakeBot())
        tracked = _FakeTrackedStore()
        cog._tracked = tracked  # type: ignore[method-assign]

        await TrackingCog.track_new.callback(  # type: ignore[attr-defined]
            cog,
            interaction,
            "asura|https://asurascans.example/series/solo-leveling",
        )

        assert interaction.followup.sends == []
        assert tracked.upserts
        assert tracked.guild_adds
        assert all(
            edit["embed"].title == "Running /track new" for edit in interaction.original_edits
        )

    asyncio.run(_run())


def test_track_new_edits_original_response_with_progress_history_on_crawler_error() -> None:
    async def _run() -> None:
        interaction = _FakeInteraction()
        cog = TrackingCog(_FakeBot(_FailingTrackCrawler()))
        tracked = _FakeTrackedStore()
        cog._tracked = tracked  # type: ignore[method-assign]

        await TrackingCog.track_new.callback(  # type: ignore[attr-defined]
            cog,
            interaction,
            "asura|https://asurascans.example/series/solo-leveling",
        )

        assert interaction.followup.sends == []
        final_embed = interaction.original_edits[-1]["embed"]
        assert final_embed.title == "Crawler Error"
        assert "Tracking failed: the crawler couldn't fetch series data." in (
            final_embed.description or ""
        )
        assert "Sent request to crawler" in (final_embed.description or "")
        assert "Fetching series: Reading latest chapters" in (final_embed.description or "")
        assert tracked.upserts == []
        assert tracked.guild_adds == []

    asyncio.run(_run())
