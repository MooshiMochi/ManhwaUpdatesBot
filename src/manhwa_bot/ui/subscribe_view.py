"""Action buttons rendered below /search, /info, and similar embeds.

A single ``SubscribeView`` is configurable: any combination of Subscribe,
Track, Bookmark, and More-Info buttons can be enabled per call site.
"""

from __future__ import annotations

import logging

import discord

from ..db.bookmarks import BookmarkStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore

_log = logging.getLogger(__name__)


class SubscribeView(discord.ui.View):
    """Interactive buttons for catalog-style embeds.

    Parameters
    ----------
    website_key, url_name:
        Identify the series in the bot DB (used by Subscribe/Track/Bookmark).
    series_url:
        Required for the Track button (the crawler ``track_series`` flow
        takes a full URL) and used as a hyperlink target on responses.
    show_track_button:
        Kept for call-site compatibility. V1 exposes one combined
        "Track and Subscribe" action instead of a separate Track button.
    show_bookmark_button:
        Adds a "Bookmark" button.
    show_info_button:
        Adds a "More info" button — opens the series in the catalog cog's
        info flow. Useful below /search results.
    """

    def __init__(
        self,
        *,
        website_key: str,
        url_name: str,
        series_url: str | None = None,
        show_track_button: bool = False,
        show_bookmark_button: bool = False,
        show_info_button: bool = False,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._website_key = website_key
        self._url_name = url_name
        self._series_url = series_url
        self._build(
            show_track_button=show_track_button,
            show_bookmark_button=show_bookmark_button,
            show_info_button=show_info_button,
        )

    def _build(
        self,
        *,
        show_track_button: bool,
        show_bookmark_button: bool,
        show_info_button: bool,
    ) -> None:
        track_and_sub_btn = discord.ui.Button(
            label="Track and Subscribe",
            style=discord.ButtonStyle.blurple,
            emoji="📚",
            row=1,
        )
        track_and_sub_btn.callback = self._on_subscribe
        self.add_item(track_and_sub_btn)

        info_btn = discord.ui.Button(
            label="More Info" if show_info_button else "\u200b",
            style=discord.ButtonStyle.blurple if show_info_button else discord.ButtonStyle.grey,
            disabled=not show_info_button,
            row=1,
        )
        info_btn.callback = self._on_more_info
        self.add_item(info_btn)

        bookmark_btn = discord.ui.Button(
            label="Bookmark",
            style=discord.ButtonStyle.blurple,
            emoji="🔖",
            disabled=not show_bookmark_button,
            row=1,
        )
        bookmark_btn.callback = self._on_bookmark
        self.add_item(bookmark_btn)

    async def _on_subscribe(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Subscriptions are server-specific. Run this in a server.",
                ephemeral=True,
            )
            return

        bot: discord.Client = interaction.client
        sub_store = SubscriptionStore(bot.db)  # type: ignore[attr-defined]
        tracked_store = TrackedStore(bot.db)  # type: ignore[attr-defined]

        tracked = await tracked_store.find(self._website_key, self._url_name)
        if tracked is None:
            await interaction.response.send_message(
                "This series isn't tracked in any server yet — ask an admin to `/track new` first.",
                ephemeral=True,
            )
            return

        try:
            await sub_store.subscribe(
                interaction.user.id,
                interaction.guild.id,
                self._website_key,
                self._url_name,
            )
        except Exception:
            _log.exception(
                "subscribe button failed for %s:%s",
                self._website_key,
                self._url_name,
            )
            await interaction.response.send_message(
                "Failed to subscribe — please try again.", ephemeral=True
            )
            return

        link = (
            f"[{tracked.title}]({tracked.series_url})"
            if tracked.series_url
            else f"**{tracked.title}**"
        )
        await interaction.response.send_message(
            f"Subscribed to {link}! You'll receive DM notifications when new chapters drop.",
            ephemeral=True,
        )

    async def _on_track(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Tracking is server-specific. Run this in a server.", ephemeral=True
            )
            return

        member = interaction.guild.get_member(interaction.user.id)
        if member is None or not member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "You need the **Manage Roles** permission to track series in this server.",
                ephemeral=True,
            )
            return

        url = self._series_url or self._url_name
        await interaction.response.send_message(
            f"Use `/track new manga_url:{url}` to track this series in this server.",
            ephemeral=True,
        )

    async def _on_bookmark(self, interaction: discord.Interaction) -> None:
        bot: discord.Client = interaction.client
        bookmark_store = BookmarkStore(bot.db)  # type: ignore[attr-defined]

        existing = await bookmark_store.get_bookmark(
            interaction.user.id, self._website_key, self._url_name
        )
        if existing is not None:
            await interaction.response.send_message(
                "You already have a bookmark for this series — use `/bookmark view`.",
                ephemeral=True,
            )
            return

        try:
            await bookmark_store.upsert_bookmark(
                interaction.user.id,
                self._website_key,
                self._url_name,
                folder="Reading",
                last_read_chapter="—",
                last_read_index=0,
            )
        except Exception:
            _log.exception(
                "bookmark button failed for %s:%s",
                self._website_key,
                self._url_name,
            )
            await interaction.response.send_message(
                "Failed to bookmark — please try again.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "Bookmark added to **Reading**. Use `/bookmark update` to set a chapter.",
            ephemeral=True,
        )

    async def _on_more_info(self, interaction: discord.Interaction) -> None:
        url = self._series_url or self._url_name
        await interaction.response.send_message(
            f"Run `/info series:{url}` for the full details.",
            ephemeral=True,
        )
