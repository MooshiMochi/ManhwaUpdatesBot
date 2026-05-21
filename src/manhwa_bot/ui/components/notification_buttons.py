"""Persistent DynamicItem buttons for the chapter update notification view."""

from __future__ import annotations

import logging
import re
from typing import Any

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
    ) -> "MarkReadButton":
        return cls(match["wk"], match["un"], int(match["idx"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        # Wired in Task 6.
        await interaction.response.send_message("Not yet implemented.", ephemeral=True)


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
    ) -> "BookmarkButton":
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Not yet implemented.", ephemeral=True)


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
    ) -> "SubscribeToggleButton":
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Not yet implemented.", ephemeral=True)


# Re-exports referenced by stores when Task 6 wires the callbacks.
__all__ = [
    "ALL_UPDATE_BUTTONS",
    "BOOKMARK_TEMPLATE",
    "BookmarkButton",
    "BookmarkStore",
    "DmSettingsStore",
    "GuildSettingsStore",
    "MARK_READ_TEMPLATE",
    "MarkReadButton",
    "SUBSCRIBE_TEMPLATE",
    "SubscribeToggleButton",
    "SubscriptionStore",
    "TrackedStore",
    "UPDATE_BUTTON_KEYS",
    "UPDATE_BUTTON_LABELS",
]
