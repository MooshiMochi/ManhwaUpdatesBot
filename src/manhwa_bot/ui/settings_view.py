"""SettingsView — ephemeral guild config UI for /settings."""

from __future__ import annotations

import logging
from typing import Any

import discord

from ..db.guild_settings import GuildSettings, GuildSettingsStore

_log = logging.getLogger(__name__)

_REQUIRED_GUILD_PERMS = discord.Permissions(
    manage_roles=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    use_external_emojis=True,
)
_REQUIRED_CHANNEL_PERMS = discord.Permissions(
    send_messages=True,
    embed_links=True,
    attach_files=True,
    use_external_emojis=True,
)


def _collect_warnings(
    settings: GuildSettings | None,
    guild: discord.Guild,
    me: discord.Member,
) -> list[str]:
    warnings: list[str] = []

    missing_guild = [
        name.replace("_", " ").title()
        for name, has_it in me.guild_permissions
        if getattr(_REQUIRED_GUILD_PERMS, name, False) and not has_it
    ]
    if missing_guild:
        warnings.append(f"❌ Bot missing guild permissions: `{', '.join(missing_guild)}`")

    if settings is None:
        return warnings

    for attr, label in (
        ("notifications_channel_id", "Notifications channel"),
        ("system_alerts_channel_id", "System alerts channel"),
    ):
        ch_id = getattr(settings, attr)
        if not ch_id:
            continue
        ch = guild.get_channel(ch_id)
        if ch is None:
            warnings.append(f"⚠️ {label} not found — it may have been deleted.")
        elif isinstance(ch, discord.TextChannel):
            my_perms = ch.permissions_for(me)
            missing = [
                name.replace("_", " ").title()
                for name, has_it in my_perms
                if getattr(_REQUIRED_CHANNEL_PERMS, name, False) and not has_it
            ]
            if missing:
                warnings.append(f"❌ Missing permissions in {ch.mention}: `{', '.join(missing)}`")

    if settings.default_ping_role_id:
        role = guild.get_role(settings.default_ping_role_id)
        if role is None:
            warnings.append("⚠️ Default ping role not found — it may have been deleted.")

    return warnings


def _build_settings_embed(
    settings: GuildSettings | None,
    scanlator_overrides: list[dict],
    warnings: list[str],
) -> discord.Embed:
    notif_ch = (
        f"<#{settings.notifications_channel_id}>"
        if settings and settings.notifications_channel_id
        else "Not set"
    )
    alerts_ch = (
        f"<#{settings.system_alerts_channel_id}>"
        if settings and settings.system_alerts_channel_id
        else "Not set"
    )
    ping_role = (
        f"<@&{settings.default_ping_role_id}>"
        if settings and settings.default_ping_role_id
        else "Not set"
    )
    paid = "✅" if settings and settings.paid_chapter_notifs else "❌"

    override_lines = [
        f"• **{r['website_key']}** → <#{r['channel_id']}>" for r in scanlator_overrides
    ]
    overrides_text = "\n".join(override_lines) if override_lines else "None"

    desc = (
        f"**#️⃣ Notifications Channel:** {notif_ch}\n"
        f"​ ​ ​ **^** `Chapter update notifications are sent here.`\n"
        f"**❗ System Alerts Channel:** {alerts_ch}\n"
        f"​ ​ ​ **^** `Critical system alerts are sent here.`\n"
        f"**🔔 Default Ping Role:** {ping_role}\n"
        f"​ ​ ​ **^** `This role is pinged for chapter updates.`\n"
        f"**💰 Paid Chapter Notifs:** {paid}\n"
        f"​ ​ ​ **^** `Toggle with the button below.`\n"
        f"**🗨️ Per-Scanlator Channels:**\n{overrides_text}"
    )

    colour = discord.Colour.red() if warnings else discord.Colour.blurple()
    embed = discord.Embed(title="Server Settings", description=desc, colour=colour)
    if warnings:
        embed.add_field(name="⚠️ Warnings", value="\n".join(warnings), inline=False)
    return embed


class SettingsView(discord.ui.View):
    """Main ephemeral settings view.

    Layout (4 active rows):
      Row 0 — ChannelSelect: notifications channel
      Row 1 — ChannelSelect: system alerts channel
      Row 2 — RoleSelect:    default ping role
      Row 3 — Button: toggle paid chapters  |  Button: open scanlator sub-view
    """

    def __init__(
        self,
        bot: Any,
        guild_id: int,
        settings: GuildSettings | None,
        scanlator_overrides: list[dict],
    ) -> None:
        super().__init__(timeout=2 * 24 * 60 * 60)  # 2-day timeout
        self._bot = bot
        self._guild_id = guild_id
        self._store = GuildSettingsStore(bot.db)
        self._settings = settings
        self._scanlator_overrides = scanlator_overrides
        self._sync_paid_button()

    def _sync_paid_button(self) -> None:
        paid = self._settings.paid_chapter_notifs if self._settings else False
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == "toggle_paid_notifs":
                item.label = f"💰 Paid Chapters: {'✅' if paid else '❌'}"
                break

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if member and member.guild_permissions.manage_guild:
            return True
        await interaction.response.send_message(
            "You need the **Manage Guild** permission to use this.", ephemeral=True
        )
        return False

    async def _refresh(self, interaction: discord.Interaction) -> None:
        self._settings = await self._store.get(self._guild_id)
        self._scanlator_overrides = await self._store.list_scanlator_channels(self._guild_id)
        guild = interaction.guild
        me = guild.me if guild else None
        warnings = _collect_warnings(self._settings, guild, me) if guild and me else []
        self._sync_paid_button()
        embed = _build_settings_embed(self._settings, self._scanlator_overrides, warnings)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="📢 Notifications channel…",
        row=0,
    )
    async def _notifications_channel(
        self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ) -> None:
        await self._store.set_notifications_channel(self._guild_id, select.values[0].id)
        await self._refresh(interaction)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="❗ System alerts channel…",
        row=1,
    )
    async def _system_alerts_channel(
        self, interaction: discord.Interaction, select: discord.ui.ChannelSelect
    ) -> None:
        await self._store.set_system_alerts_channel(self._guild_id, select.values[0].id)
        await self._refresh(interaction)

    @discord.ui.select(
        cls=discord.ui.RoleSelect,
        placeholder="🔔 Default ping role…",
        row=2,
    )
    async def _default_ping_role(
        self, interaction: discord.Interaction, select: discord.ui.RoleSelect
    ) -> None:
        await self._store.set_default_ping_role(self._guild_id, select.values[0].id)
        await self._refresh(interaction)

    @discord.ui.button(
        label="💰 Paid Chapters: ❌",
        style=discord.ButtonStyle.secondary,
        custom_id="toggle_paid_notifs",
        row=3,
    )
    async def _toggle_paid(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        current = self._settings.paid_chapter_notifs if self._settings else False
        await self._store.set_paid_chapter_notifs(self._guild_id, not current)
        await self._refresh(interaction)

    @discord.ui.button(
        label="🗨️ Per-Scanlator Channels…",
        style=discord.ButtonStyle.primary,
        row=3,
    )
    async def _open_scanlator_channels(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        overrides = await self._store.list_scanlator_channels(self._guild_id)
        view = ScanlatorChannelsView(self._bot, self._guild_id, overrides, parent=self)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class _RemoveButton(discord.ui.Button["ScanlatorChannelsView"]):
    """Dynamic remove button for one scanlator override entry."""

    def __init__(self, parent_view: ScanlatorChannelsView, website_key: str, *, row: int) -> None:
        super().__init__(
            label=f"✕ {website_key}",
            style=discord.ButtonStyle.danger,
            row=row,
        )
        self._scanlator_view = parent_view
        self._website_key = website_key

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._scanlator_view._store.clear_scanlator_channel(
            self._scanlator_view._guild_id, self._website_key
        )
        overrides = await self._scanlator_view._store.list_scanlator_channels(
            self._scanlator_view._guild_id
        )
        self._scanlator_view._overrides = overrides
        self._scanlator_view._rebuild_items()
        await interaction.response.edit_message(
            embed=self._scanlator_view.build_embed(), view=self._scanlator_view
        )


class ScanlatorChannelsView(discord.ui.View):
    """Sub-view listing per-scanlator channel overrides with remove + add buttons."""

    def __init__(
        self,
        bot: Any,
        guild_id: int,
        overrides: list[dict],
        *,
        parent: SettingsView,
    ) -> None:
        super().__init__(timeout=2 * 24 * 60 * 60)
        self._bot = bot
        self._guild_id = guild_id
        self._overrides = overrides
        self._parent = parent
        self._store = GuildSettingsStore(bot.db)
        self._rebuild_items()

    def build_embed(self) -> discord.Embed:
        if not self._overrides:
            desc = "No per-scanlator overrides set.\nUse **+ Add Override** to add one."
        else:
            lines = [f"• **{r['website_key']}** → <#{r['channel_id']}>" for r in self._overrides]
            desc = "\n".join(lines)
        return discord.Embed(
            title="Per-Scanlator Channel Overrides",
            description=desc,
            colour=discord.Colour.blurple(),
        )

    def _rebuild_items(self) -> None:
        self.clear_items()
        # Up to 20 overrides across rows 0-3 (5 per row); row 4 reserved for Add + Back
        for i, row in enumerate(self._overrides[:20]):
            self.add_item(_RemoveButton(self, row["website_key"], row=i // 5))

        add_btn = discord.ui.Button(
            label="+ Add Override",
            style=discord.ButtonStyle.success,
            row=4,
        )
        add_btn.callback = self._on_add_override
        self.add_item(add_btn)

        back_btn = discord.ui.Button(
            label="← Back",
            style=discord.ButtonStyle.secondary,
            row=4,
        )
        back_btn.callback = self._on_back
        self.add_item(back_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if member and member.guild_permissions.manage_guild:
            return True
        await interaction.response.send_message(
            "You need the **Manage Guild** permission to use this.", ephemeral=True
        )
        return False

    async def _on_add_override(self, interaction: discord.Interaction) -> None:
        bot = self._bot
        ttl = bot.config.supported_websites_cache.ttl_seconds

        async def _loader() -> list[str]:
            data = await bot.crawler.request("supported_websites")
            return [
                w.get("key") or w.get("website_key")
                for w in data.get("websites", [])
                if w.get("key") or w.get("website_key")
            ]

        try:
            keys: list[str] = await bot.websites_cache.get_or_set("websites", _loader, ttl)
        except Exception:
            _log.exception("Failed to load website keys for scanlator override")
            keys = []

        if not keys:
            await interaction.response.send_message(
                "Could not load website list from crawler. Try again later.", ephemeral=True
            )
            return

        view = ScanlatorAddView(bot, self._guild_id, keys, parent=self)
        embed = discord.Embed(
            title="Add Per-Scanlator Override",
            description=(
                "1️⃣ Select a **website / scanlator** from the first dropdown.\n"
                "2️⃣ Select the **channel** to route its notifications to.\n"
                "3️⃣ Click **Save**."
            ),
            colour=discord.Colour.green(),
        )
        await interaction.response.edit_message(embed=embed, view=view)

    async def _on_back(self, interaction: discord.Interaction) -> None:
        parent = self._parent
        parent._scanlator_overrides = self._overrides
        guild = interaction.guild
        me = guild.me if guild else None
        warnings = _collect_warnings(parent._settings, guild, me) if guild and me else []
        parent._sync_paid_button()
        embed = _build_settings_embed(parent._settings, parent._scanlator_overrides, warnings)
        await interaction.response.edit_message(embed=embed, view=parent)


class ScanlatorAddView(discord.ui.View):
    """Transient view for selecting website key + channel when adding a scanlator override."""

    def __init__(
        self,
        bot: Any,
        guild_id: int,
        website_keys: list[str],
        *,
        parent: ScanlatorChannelsView,
    ) -> None:
        super().__init__(timeout=300)
        self._bot = bot
        self._guild_id = guild_id
        self._parent = parent
        self._store = GuildSettingsStore(bot.db)
        self._selected_key: str | None = None
        self._selected_channel_id: int | None = None

        options = [discord.SelectOption(label=k, value=k) for k in website_keys[:25]]
        self._key_select: discord.ui.Select = discord.ui.Select(
            placeholder="Select a website / scanlator…",
            options=options,
            row=0,
        )
        self._key_select.callback = self._on_key_selected
        self.add_item(self._key_select)

        self._ch_select: discord.ui.ChannelSelect = discord.ui.ChannelSelect(
            placeholder="Select a channel…",
            channel_types=[discord.ChannelType.text],
            row=1,
        )
        self._ch_select.callback = self._on_channel_selected
        self.add_item(self._ch_select)

        save_btn = discord.ui.Button(label="Save", style=discord.ButtonStyle.success, row=2)
        save_btn.callback = self._on_save
        self.add_item(save_btn)

        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

    def _status_embed(self) -> discord.Embed:
        key_text = f"**{self._selected_key}**" if self._selected_key else "_not selected_"
        ch_text = (
            f"<#{self._selected_channel_id}>" if self._selected_channel_id else "_not selected_"
        )
        return discord.Embed(
            title="Add Per-Scanlator Override",
            description=(
                f"**Website:** {key_text}\n"
                f"**Channel:** {ch_text}\n\n"
                "Select both, then click **Save**."
            ),
            colour=discord.Colour.green(),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if member and member.guild_permissions.manage_guild:
            return True
        await interaction.response.send_message(
            "You need the **Manage Guild** permission to use this.", ephemeral=True
        )
        return False

    async def _on_key_selected(self, interaction: discord.Interaction) -> None:
        self._selected_key = self._key_select.values[0]
        await interaction.response.edit_message(embed=self._status_embed(), view=self)

    async def _on_channel_selected(self, interaction: discord.Interaction) -> None:
        self._selected_channel_id = self._ch_select.values[0].id
        await interaction.response.edit_message(embed=self._status_embed(), view=self)

    async def _on_save(self, interaction: discord.Interaction) -> None:
        if not self._selected_key or not self._selected_channel_id:
            await interaction.response.send_message(
                "Please select both a website and a channel before saving.", ephemeral=True
            )
            return
        await self._store.set_scanlator_channel(
            self._guild_id, self._selected_key, self._selected_channel_id
        )
        overrides = await self._store.list_scanlator_channels(self._guild_id)
        self._parent._overrides = overrides
        self._parent._rebuild_items()
        await interaction.response.edit_message(embed=self._parent.build_embed(), view=self._parent)

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=self._parent.build_embed(), view=self._parent)
