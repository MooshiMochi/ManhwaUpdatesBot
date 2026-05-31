"""Migrate cog — guides users through remapping leftover V1 series.

The companion migration script in `crawler_backend` (`src/scripts/migrate_v1_database.py`)
re-fetches every supported V1 series into V2. For V1 series whose website is
disabled or never supported in V2, it writes a `migration_leftovers.json` file
keyed by Discord user and guild ids.

This cog presents those leftovers interactively:

* ``/migrate leftovers`` — user-scoped. Walks each invoking user through their
  subscription and bookmark leftovers. Search across V2 sites, pick a match,
  confirm, and the bot writes the resulting subscription/bookmark.

* ``/migrate guild_leftovers`` — guild-scoped. Same flow for the guild's
  tracked-series leftovers. Requires Manage Roles.

Resolutions (including skips) are recorded in the ``migration_resolutions``
table so re-invoking the command never re-prompts for the same row.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from ..crawler.errors import CrawlerError, Disconnected, RequestTimeout
from ..db.bookmarks import BookmarkStore
from ..db.migration_resolutions import MigrationResolutionsStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore

_log = logging.getLogger(__name__)

_DEFAULT_LEFTOVERS_PATH = "data/migration_leftovers.json"
_REPO_ROOT = Path(__file__).resolve().parents[3]  # .../ManhwaUpdatesBot
_SEARCH_LIMIT = 8
_SEARCH_TIMEOUT_MS = 20000


def _leftovers_path() -> Path:
    env = os.environ.get("MIGRATION_LEFTOVERS_PATH")
    if env:
        return Path(env)
    cwd_relative = Path(_DEFAULT_LEFTOVERS_PATH)
    if cwd_relative.exists():
        return cwd_relative
    return _REPO_ROOT / _DEFAULT_LEFTOVERS_PATH


def _load_leftovers() -> dict[str, Any] | None:
    path = _leftovers_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("could not read leftovers JSON %s: %s", path, exc)
        return None


def _shorten(s: str, n: int = 80) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ─────────────────────── leftover collection ───────────────────────


class _UserLeftover:
    __slots__ = ("extra", "scope", "v1_scanlator", "v1_title", "v1_url")

    def __init__(
        self,
        scope: str,
        v1_scanlator: str,
        v1_url: str,
        v1_title: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.scope = scope  # 'subscription' | 'bookmark'
        self.v1_scanlator = v1_scanlator
        self.v1_url = v1_url
        self.v1_title = v1_title
        self.extra = extra or {}

    @property
    def key(self) -> tuple[str, str]:
        return self.v1_scanlator, self.v1_url

    def select_label(self) -> str:
        prefix = "Sub" if self.scope == "subscription" else "BM "
        return _shorten(f"[{prefix}] {self.v1_title}", 100)

    def select_description(self) -> str:
        return _shorten(f"{self.v1_scanlator} · {self.v1_url}", 100)


def _gather_user_leftovers(
    payload: dict[str, Any], user_id: int, already_resolved: set[tuple[str, str]]
) -> list[_UserLeftover]:
    users = payload.get("users") or {}
    entry = users.get(str(user_id)) or {}
    out: list[_UserLeftover] = []
    for sub in entry.get("subscriptions") or []:
        key = (sub["v1_scanlator"], sub["v1_url"])
        if key in already_resolved:
            continue
        out.append(
            _UserLeftover(
                "subscription",
                sub["v1_scanlator"],
                sub["v1_url"],
                sub.get("v1_title") or sub["v1_url"],
                {"guild_id": sub.get("guild_id")},
            )
        )
    for bm in entry.get("bookmarks") or []:
        key = (bm["v1_scanlator"], bm["v1_url"])
        if key in already_resolved:
            continue
        out.append(
            _UserLeftover(
                "bookmark",
                bm["v1_scanlator"],
                bm["v1_url"],
                bm.get("v1_title") or bm["v1_url"],
                {"folder": bm.get("folder"), "last_read_index": bm.get("last_read_index")},
            )
        )
    return out


def _gather_guild_leftovers(
    payload: dict[str, Any], guild_id: int, already_resolved: set[tuple[str, str]]
) -> list[_UserLeftover]:
    items = (payload.get("guild_tracked") or {}).get(str(guild_id)) or []
    out: list[_UserLeftover] = []
    for it in items:
        key = (it["v1_scanlator"], it["v1_url"])
        if key in already_resolved:
            continue
        out.append(
            _UserLeftover(
                "guild_tracking",
                it["v1_scanlator"],
                it["v1_url"],
                it.get("v1_title") or it["v1_url"],
                {"role_id": it.get("role_id")},
            )
        )
    return out


# ─────────────────────── UI views ───────────────────────


class _PickLeftoverView(discord.ui.View):
    def __init__(
        self,
        cog: MigrateCog,
        invoker_id: int,
        leftovers: list[_UserLeftover],
        *,
        guild_id_override: int | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self._cog = cog
        self._invoker_id = invoker_id
        self._guild_override = guild_id_override
        self._leftovers = {f"{i}": lo for i, lo in enumerate(leftovers[:25])}

        options = [
            discord.SelectOption(
                label=lo.select_label(),
                description=lo.select_description(),
                value=k,
            )
            for k, lo in self._leftovers.items()
        ]
        select = discord.ui.Select(
            placeholder="Pick a leftover series to remap…",
            options=options,
            min_values=1,
            max_values=1,
        )
        select.callback = self._on_pick  # type: ignore[assignment]
        self.add_item(select)

        skip = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Skip all (mark as no-match)",
            row=1,
        )
        skip.callback = self._on_skip_all  # type: ignore[assignment]
        self.add_item(skip)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                "This wizard belongs to another user.", ephemeral=True
            )
            return False
        return True

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        value = interaction.data["values"][0]  # type: ignore[index,call-overload]
        lo = self._leftovers[value]
        await self._cog._begin_remap(interaction, lo, guild_id_override=self._guild_override)

    async def _on_skip_all(self, interaction: discord.Interaction) -> None:
        for lo in self._leftovers.values():
            owner = self._guild_override or self._invoker_id
            await self._cog._resolutions.record(
                lo.scope, owner, lo.v1_scanlator, lo.v1_url, None, None
            )
        await interaction.response.edit_message(
            content=f"Marked {len(self._leftovers)} leftovers as skipped. "
            "Run the command again if more remain.",
            view=None,
        )


class _PickCandidateView(discord.ui.View):
    def __init__(
        self,
        cog: MigrateCog,
        invoker_id: int,
        lo: _UserLeftover,
        candidates: list[dict[str, Any]],
        *,
        guild_id_override: int | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self._cog = cog
        self._invoker_id = invoker_id
        self._lo = lo
        self._guild_override = guild_id_override
        self._candidates = {f"{i}": c for i, c in enumerate(candidates[:25])}

        options = [
            discord.SelectOption(
                label=_shorten(c.get("title") or "(no title)", 100),
                description=_shorten(
                    f"{c.get('website_key', '?')} · {c.get('url_name', '?')}", 100
                ),
                value=k,
            )
            for k, c in self._candidates.items()
        ]
        if options:
            select = discord.ui.Select(
                placeholder="Pick the correct match…",
                options=options,
                min_values=1,
                max_values=1,
            )
            select.callback = self._on_pick  # type: ignore[assignment]
            self.add_item(select)

        skip = discord.ui.Button(
            style=discord.ButtonStyle.secondary,
            label="Skip this leftover",
            row=1,
        )
        skip.callback = self._on_skip  # type: ignore[assignment]
        self.add_item(skip)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                "This wizard belongs to another user.", ephemeral=True
            )
            return False
        return True

    async def _on_pick(self, interaction: discord.Interaction) -> None:
        value = interaction.data["values"][0]  # type: ignore[index,call-overload]
        choice = self._candidates[value]
        await interaction.response.defer(thinking=True, ephemeral=True)
        await self._cog._apply_remap(
            interaction,
            self._lo,
            choice,
            guild_id_override=self._guild_override,
        )

    async def _on_skip(self, interaction: discord.Interaction) -> None:
        owner = self._guild_override or self._invoker_id
        await self._cog._resolutions.record(
            self._lo.scope, owner, self._lo.v1_scanlator, self._lo.v1_url, None, None
        )
        await interaction.response.edit_message(
            content=f"Skipped **{self._lo.v1_title}**. Run the command again "
            "to see the next leftover.",
            view=None,
        )


# ─────────────────────── cog ───────────────────────


class MigrateCog(commands.Cog, name="Migrate"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._subs = SubscriptionStore(bot.db)  # type: ignore[attr-defined]
        self._bookmarks = BookmarkStore(bot.db)  # type: ignore[attr-defined]
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]
        self._resolutions = MigrationResolutionsStore(bot.db)  # type: ignore[attr-defined]

    migrate = app_commands.Group(
        name="migrate",
        description="Remap V1 series whose website is no longer supported.",
        guild_only=False,
    )

    # -- /migrate leftovers ----------------------------------------------------

    @migrate.command(
        name="leftovers",
        description="Walk through your unresolved V1 subscriptions and bookmarks.",
    )
    async def leftovers(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        payload = _load_leftovers()
        if payload is None:
            await interaction.followup.send(
                "No migration leftovers file was found on this host.",
                ephemeral=True,
            )
            return

        # Gather (subscription + bookmark) leftovers minus already-resolved.
        resolved_sub = await self._resolutions.resolved_keys("subscription", interaction.user.id)
        resolved_bm = await self._resolutions.resolved_keys("bookmark", interaction.user.id)
        already = resolved_sub | resolved_bm
        items = _gather_user_leftovers(payload, interaction.user.id, already)

        if not items:
            await interaction.followup.send("You have no unresolved leftovers. 🎉", ephemeral=True)
            return

        await interaction.followup.send(
            content=(
                f"You have **{len(items)}** unresolved V1 leftovers "
                f"(subscriptions + bookmarks). Pick one to remap onto a supported "
                f"V2 site, or skip all to dismiss them."
            ),
            view=_PickLeftoverView(self, interaction.user.id, items),
            ephemeral=True,
        )

    # -- /migrate guild_leftovers ---------------------------------------------

    @migrate.command(
        name="guild_leftovers",
        description="(Mods) Walk through this guild's unresolved tracked leftovers.",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_roles=True)
    async def guild_leftovers(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        if interaction.guild_id is None:
            await interaction.followup.send("Run this from inside a guild.", ephemeral=True)
            return

        payload = _load_leftovers()
        if payload is None:
            await interaction.followup.send(
                "No migration leftovers file was found on this host.",
                ephemeral=True,
            )
            return

        resolved = await self._resolutions.resolved_keys("guild_tracking", interaction.guild_id)
        items = _gather_guild_leftovers(payload, interaction.guild_id, resolved)
        if not items:
            await interaction.followup.send(
                "This guild has no unresolved tracked leftovers. 🎉", ephemeral=True
            )
            return

        await interaction.followup.send(
            content=(
                f"This guild has **{len(items)}** unresolved tracked leftovers. "
                f"Pick one to remap to a supported V2 site, or skip all."
            ),
            view=_PickLeftoverView(
                self, interaction.user.id, items, guild_id_override=interaction.guild_id
            ),
            ephemeral=True,
        )

    # -- shared remap flow ----------------------------------------------------

    async def _begin_remap(
        self,
        interaction: discord.Interaction,
        lo: _UserLeftover,
        *,
        guild_id_override: int | None,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "search",
                request_id=uuid.uuid4().hex,
                query=lo.v1_title,
                limit=_SEARCH_LIMIT,
                timeout_ms=_SEARCH_TIMEOUT_MS,
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(
                f"Search failed: {exc}",
                ephemeral=True,
            )
            return

        results = (data or {}).get("results") or []
        if not results:
            await interaction.followup.send(
                content=(
                    f"No matches for **{lo.v1_title}** on any supported site. "
                    f"Use the Skip button to dismiss this leftover."
                ),
                view=_PickCandidateView(
                    self, interaction.user.id, lo, [], guild_id_override=guild_id_override
                ),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            content=(
                f"Top {len(results[:25])} matches for **{lo.v1_title}** "
                f"(V1: `{lo.v1_scanlator}`). Pick the correct one."
            ),
            view=_PickCandidateView(
                self,
                interaction.user.id,
                lo,
                results,
                guild_id_override=guild_id_override,
            ),
            ephemeral=True,
        )

    async def _apply_remap(
        self,
        interaction: discord.Interaction,
        lo: _UserLeftover,
        chosen: dict[str, Any],
        *,
        guild_id_override: int | None,
    ) -> None:
        website_key = chosen.get("website_key")
        series_url = chosen.get("series_url") or chosen.get("url")
        if not (website_key and series_url):
            await interaction.followup.send(
                "Selected entry is missing a website key or URL — cannot track.",
                ephemeral=True,
            )
            return

        try:
            track_data = await self.bot.crawler.request(  # type: ignore[attr-defined]
                "track",
                website_key=website_key,
                series_url=series_url,
            )
        except (CrawlerError, RequestTimeout, Disconnected) as exc:
            await interaction.followup.send(
                f"Tracking failed: {exc}",
                ephemeral=True,
            )
            return

        url_name = (track_data or {}).get("url_name") or chosen.get("url_name")
        title = (track_data or {}).get("title") or chosen.get("title") or lo.v1_title
        cover = (track_data or {}).get("cover_url") or chosen.get("cover_url")
        status = (track_data or {}).get("status")
        if not url_name:
            await interaction.followup.send(
                "Tracking returned no url_name — cannot record bookmark/subscription.",
                ephemeral=True,
            )
            return

        # Make sure tracked_series row exists before subscribe/bookmark writes.
        await self._tracked.upsert_series(
            website_key=website_key,
            url_name=url_name,
            series_url=series_url,
            title=title,
            cover_url=cover,
            status=status,
        )

        owner_for_resolution = guild_id_override or interaction.user.id

        if lo.scope == "subscription":
            guild_id = int(lo.extra.get("guild_id") or interaction.guild_id or 0)
            await self._subs.subscribe(
                user_id=interaction.user.id,
                guild_id=guild_id,
                website_key=website_key,
                url_name=url_name,
            )
            msg = (
                f"Subscribed you to **{title}** on `{website_key}`. "
                f"Notifications go to your DMs (or this guild)."
            )
        elif lo.scope == "bookmark":
            folder = lo.extra.get("folder") or "Reading"
            last_read = lo.extra.get("last_read_index")
            await self._bookmarks.upsert_bookmark(
                user_id=interaction.user.id,
                website_key=website_key,
                url_name=url_name,
                folder=folder,
                last_read_index=last_read,
            )
            msg = f"Bookmarked **{title}** on `{website_key}` in folder *{folder}*" + (
                f" (last read #{last_read})." if last_read else "."
            )
        elif lo.scope == "guild_tracking":
            if guild_id_override is None:
                await interaction.followup.send(
                    "Guild tracking remap must be invoked from /migrate guild_leftovers.",
                    ephemeral=True,
                )
                return
            await self._tracked.add_to_guild(
                guild_id=guild_id_override,
                website_key=website_key,
                url_name=url_name,
                ping_role_id=lo.extra.get("role_id"),
            )
            msg = f"Added **{title}** on `{website_key}` to this guild's tracked list."
        else:
            await interaction.followup.send(f"Unknown scope `{lo.scope}`.", ephemeral=True)
            return

        await self._resolutions.record(
            lo.scope,
            owner_for_resolution,
            lo.v1_scanlator,
            lo.v1_url,
            website_key,
            url_name,
        )

        await interaction.followup.send(
            f"{msg}\nRun the command again to handle the next leftover.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MigrateCog(bot))
