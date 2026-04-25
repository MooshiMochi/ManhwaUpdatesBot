"""Subscribe / track buttons rendered below search-result and info embeds."""

from __future__ import annotations

import logging

import discord

from ..db.subscriptions import SubscriptionStore

_log = logging.getLogger(__name__)


class SubscribeView(discord.ui.View):
    """Attached below search and info embeds to let users subscribe in one click.

    Parameters
    ----------
    website_key:
        The scanlator key (e.g. ``"asura"``).
    url_name:
        The series slug / url_name as stored in the DB.
    show_track_button:
        When ``True`` (e.g. on ``/info`` responses) also shows a
        "Track in this server" button, but only enables it when the invoker
        has ``manage_roles``.  Full implementation deferred to the tracking
        cog (phase 7); the button currently directs users to ``/track new``.
    timeout:
        Seconds before the view stops responding (default 300).
    """

    def __init__(
        self,
        *,
        website_key: str,
        url_name: str,
        show_track_button: bool = False,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._website_key = website_key
        self._url_name = url_name
        self._build(show_track_button=show_track_button)

    def _build(self, *, show_track_button: bool) -> None:
        sub_btn = discord.ui.Button(
            label="Subscribe to updates",
            style=discord.ButtonStyle.green,
            emoji="🔔",
            row=1,
        )
        sub_btn.callback = self._on_subscribe
        self.add_item(sub_btn)

        if show_track_button:
            track_btn = discord.ui.Button(
                label="Track in this server",
                style=discord.ButtonStyle.blurple,
                emoji="📌",
                row=1,
            )
            track_btn.callback = self._on_track
            self.add_item(track_btn)

    async def _on_subscribe(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Subscriptions are server-specific. Run this command in a server.",
                ephemeral=True,
            )
            return

        bot: discord.Client = interaction.client
        store = SubscriptionStore(bot.db)  # type: ignore[attr-defined]
        try:
            await store.subscribe(
                interaction.user.id,
                interaction.guild.id,
                self._website_key,
                self._url_name,
            )
        except Exception:
            _log.exception("subscribe button failed for %s:%s", self._website_key, self._url_name)
            await interaction.response.send_message(
                "Failed to subscribe — please try again.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Subscribed to **{self._url_name}** ({self._website_key})! "
            "You'll receive DM notifications when new chapters drop.",
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

        # Full tracking flow is implemented in the tracking cog (phase 7).
        # For now, direct users to the slash command.
        await interaction.response.send_message(
            "Use `/track new` and paste the series URL to track it in this server.",
            ephemeral=True,
        )
