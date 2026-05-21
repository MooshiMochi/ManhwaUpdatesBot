"""Persistent DynamicItem buttons for the chapter update notification view."""

from __future__ import annotations

import logging
import re

import discord

from ...db.bookmarks import BookmarkStore
from ...db.dm_settings import DmSettingsStore
from ...db.guild_settings import GuildSettingsStore
from ...db.subscriptions import SubscriptionStore
from ...db.tracked import TrackedStore

_log = logging.getLogger(__name__)

# Canonical key order for storage + UI rendering.
UPDATE_BUTTON_KEYS: tuple[str, ...] = (
    "mark_read",
    "bookmark",
    "subscribe",
    "open_chapter",
)
ALL_UPDATE_BUTTONS: frozenset[str] = frozenset(UPDATE_BUTTON_KEYS)

# (label, emoji, description) — used by settings select + buttons.
UPDATE_BUTTON_LABELS: dict[str, tuple[str, str, str]] = {
    "mark_read": (
        "Mark Read",
        "✅",
        "Marks the chapter as read in your bookmark.",
    ),
    "bookmark": (
        "Bookmark",
        "🔖",
        "Adds this series to your Reading bookmarks.",
    ),
    "subscribe": (
        "Subscribe",
        "🔔",
        "Toggles your subscription for this series.",
    ),
    "open_chapter": (
        "Open Chapter",
        "🔗",
        "Opens the chapter URL in your browser.",
    ),
}

# Slug guard — website_key and url_name come from the schema and must never
# contain a literal `:` (custom_id delimiter).
_SLUG_RE = re.compile(r"^[^:]+$")


def _assert_slug(value: str, *, field: str) -> str:
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(f"{field}={value!r} contains a ':' which breaks custom_id parsing")
    return value


MARK_READ_TEMPLATE = r"mu:upd:mr:(?P<wk>[^:]+):(?P<un>[^:]+):(?P<idx>-?\d+)"
BOOKMARK_TEMPLATE = r"mu:upd:bm:(?P<wk>[^:]+):(?P<un>[^:]+)"
SUBSCRIBE_TEMPLATE = r"mu:upd:sub:(?P<wk>[^:]+):(?P<un>[^:]+)"


class MarkReadButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=MARK_READ_TEMPLATE,
):

    def __init__(self, website_key: str, url_name: str, chapter_index: int) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["mark_read"][0],
                emoji=UPDATE_BUTTON_LABELS["mark_read"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:mr:{wk}:{un}:{int(chapter_index)}",
            )
        )
        self.website_key = wk
        self.url_name = un
        self.chapter_index = int(chapter_index)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> MarkReadButton:
        return cls(match["wk"], match["un"], int(match["idx"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        store = BookmarkStore(pool)
        existing = await store.get_bookmark(
            interaction.user.id, self.website_key, self.url_name
        )
        chapter_index = self.chapter_index
        # The encoded index is a hint; we don't have a live chapters lookup
        # here, so trust it for the write. The bookmark browser re-resolves
        # against current series_data when the user opens it.
        chapter_text = f"Chapter index {chapter_index}"
        await store.upsert_bookmark(
            user_id=interaction.user.id,
            website_key=self.website_key,
            url_name=self.url_name,
            folder=existing.folder if existing else "Reading",
            last_read_chapter=chapter_text,
            last_read_index=chapter_index,
        )
        msg = (
            f"✅ Marked **{self.url_name}** chapter index `{chapter_index}` as read."
            if existing
            else f"✅ Bookmarked **{self.url_name}** in *Reading* and marked chapter "
            f"index `{chapter_index}` as read."
        )
        await interaction.followup.send(msg, ephemeral=True)


class BookmarkButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=BOOKMARK_TEMPLATE,
):

    def __init__(self, website_key: str, url_name: str) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["bookmark"][0],
                emoji=UPDATE_BUTTON_LABELS["bookmark"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:bm:{wk}:{un}",
            )
        )
        self.website_key = wk
        self.url_name = un

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> BookmarkButton:
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        store = BookmarkStore(pool)
        existing = await store.get_bookmark(
            interaction.user.id, self.website_key, self.url_name
        )
        if existing is None:
            await store.upsert_bookmark(
                user_id=interaction.user.id,
                website_key=self.website_key,
                url_name=self.url_name,
                folder="Reading",
            )
            msg = f"🔖 Bookmarked **{self.url_name}** in *Reading*."
        else:
            msg = (
                f"🔖 You already have **{self.url_name}** bookmarked in "
                f"*{existing.folder}*."
            )
        await interaction.followup.send(msg, ephemeral=True)


class SubscribeToggleButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=SUBSCRIBE_TEMPLATE,
):

    def __init__(self, website_key: str, url_name: str) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["subscribe"][0],
                emoji=UPDATE_BUTTON_LABELS["subscribe"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:sub:{wk}:{un}",
            )
        )
        self.website_key = wk
        self.url_name = un

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> SubscribeToggleButton:
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        tracked_store = TrackedStore(pool)
        guild_rows = await tracked_store.list_guilds_tracking(
            self.website_key, self.url_name
        )
        if not guild_rows:
            await interaction.followup.send(
                "This series isn't tracked in any server yet — ask a server admin "
                "to `/track new` it before subscribing.",
                ephemeral=True,
            )
            return
        # Prefer the guild the click came from, otherwise the first tracking row.
        chosen_guild_id: int | None = None
        for row in guild_rows:
            if interaction.guild_id is not None and int(row.guild_id) == int(
                interaction.guild_id
            ):
                chosen_guild_id = int(row.guild_id)
                break
        if chosen_guild_id is None:
            chosen_guild_id = int(guild_rows[0].guild_id)

        subs = SubscriptionStore(pool)
        already = await subs.is_subscribed(
            interaction.user.id,
            chosen_guild_id,
            self.website_key,
            self.url_name,
        )
        if already:
            await subs.unsubscribe(
                interaction.user.id,
                chosen_guild_id,
                self.website_key,
                self.url_name,
            )
            msg = f"🔔 Unsubscribed from **{self.url_name}**."
        else:
            await subs.subscribe(
                interaction.user.id,
                chosen_guild_id,
                self.website_key,
                self.url_name,
            )
            msg = f"🔔 Subscribed to **{self.url_name}**."
        await interaction.followup.send(msg, ephemeral=True)


# Re-exports referenced by stores when Task 6 wires the callbacks.
__all__ = [
    "ALL_UPDATE_BUTTONS",
    "BOOKMARK_TEMPLATE",
    "MARK_READ_TEMPLATE",
    "SUBSCRIBE_TEMPLATE",
    "UPDATE_BUTTON_KEYS",
    "UPDATE_BUTTON_LABELS",
    "BookmarkButton",
    "BookmarkStore",
    "DmSettingsStore",
    "GuildSettingsStore",
    "MarkReadButton",
    "SubscribeToggleButton",
    "SubscriptionStore",
    "TrackedStore",
]
