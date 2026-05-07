"""SettingsView — ephemeral guild config UI for /settings.

Layout matches the v1 bot's main-menu pattern:
  Row 0  — Select: pick which setting to edit (8 options).
  Row 1  — Dynamic component (ChannelSelect / RoleSelect / Boolean Select)
           swapped based on row 0 selection.
  Row 2  — Per-Scanlator Channels button + DM toggles button (premium only when in DMs).
"""

from __future__ import annotations

import logging
from typing import Any

import discord

from ..db.dm_settings import DmSettingsStore
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

    for attr, label in (
        ("default_ping_role_id", "Default ping role"),
        ("bot_manager_role_id", "Bot manager role"),
    ):
        role_id = getattr(settings, attr)
        if not role_id:
            continue
        role = guild.get_role(role_id)
        if role is None:
            warnings.append(f"⚠️ {label} not found — it may have been deleted.")
        elif role.managed:
            warnings.append(f"⚠️ {label} is bot-managed and cannot be assigned by this bot.")
        elif role >= me.top_role:
            warnings.append(
                f"⚠️ {label} is higher than the bot's top role — the bot can't assign it."
            )

    return warnings


def _bool_emoji(value: bool) -> str:
    return "✅" if value else "❌"


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
    manager_role = (
        f"<@&{settings.bot_manager_role_id}>"
        if settings and settings.bot_manager_role_id
        else "Not set"
    )
    auto_create = _bool_emoji(bool(settings and settings.auto_create_role))
    show_buttons = _bool_emoji(bool(settings and settings.show_update_buttons))
    paid = _bool_emoji(bool(settings and settings.paid_chapter_notifs))

    override_lines = [
        f"• **{r['website_key']}** → <#{r['channel_id']}>" for r in scanlator_overrides
    ]
    overrides_text = "\n".join(override_lines) if override_lines else "None"

    desc = (
        f"**#️⃣ Notifications Channel:** {notif_ch}\n"
        f"​ ​ ​ **^** `Chapter update notifications are sent here.`\n"
        f"**❗ System Alerts Channel:** {alerts_ch}\n"
        f"​ ​ ​ **^** `Critical bot alerts are sent here.`\n"
        f"**🔔 Default Ping Role:** {ping_role}\n"
        f"​ ​ ​ **^** `Pinged for chapter updates when a tracked manga has no role of its own.`\n"
        f"**🛡️ Bot Manager Role:** {manager_role}\n"
        f"​ ​ ​ **^** `Members with this role can use admin commands without Manage Server.`\n"
        f"**🪄 Auto-Create Role:** {auto_create}\n"
        f"​ ​ ​ **^** `Automatically create a role when /track new is used without a ping_role.`\n"
        f"**🔘 Show Update Buttons:** {show_buttons}\n"
        f"​ ​ ​ **^** `Show 'Mark Read' buttons on chapter update notifications.`\n"
        f"**💰 Paid Chapter Notifs:** {paid}\n"
        f"​ ​ ​ **^** `Notify subscribers about premium / locked chapters.`\n"
        f"**🗨️ Per-Scanlator Channels:**\n{overrides_text}"
    )

    colour = discord.Colour.red() if warnings else discord.Colour.blurple()
    embed = discord.Embed(title="Server Settings", description=desc, colour=colour)
    if warnings:
        embed.add_field(name="⚠️ Warnings", value="\n".join(warnings), inline=False)
    return embed


# Main-menu setting keys. Used both as the Select option `value`s and as a switch
# in `_apply_main_select` to determine which dynamic component to render in row 1.
_SETTING_NOTIFICATIONS_CHANNEL = "notifications_channel"
_SETTING_SYSTEM_ALERTS_CHANNEL = "system_alerts_channel"
_SETTING_DEFAULT_PING_ROLE = "default_ping_role"
_SETTING_BOT_MANAGER_ROLE = "bot_manager_role"
_SETTING_AUTO_CREATE_ROLE = "auto_create_role"
_SETTING_SHOW_UPDATE_BUTTONS = "show_update_buttons"
_SETTING_PAID_CHAPTER_NOTIFS = "paid_chapter_notifs"
_SETTING_SCANLATOR_CHANNELS = "scanlator_channels"

_BOOL_SETTINGS = frozenset(
    {
        _SETTING_AUTO_CREATE_ROLE,
        _SETTING_SHOW_UPDATE_BUTTONS,
        _SETTING_PAID_CHAPTER_NOTIFS,
    }
)
_CHANNEL_SETTINGS = frozenset({_SETTING_NOTIFICATIONS_CHANNEL, _SETTING_SYSTEM_ALERTS_CHANNEL})
_ROLE_SETTINGS = frozenset({_SETTING_DEFAULT_PING_ROLE, _SETTING_BOT_MANAGER_ROLE})


_MAIN_OPTIONS: list[discord.SelectOption] = [
    discord.SelectOption(
        label="Set the updates channel",
        value=_SETTING_NOTIFICATIONS_CHANNEL,
        emoji="#️⃣",
        description="Where chapter update notifications are sent.",
    ),
    discord.SelectOption(
        label="Set Default ping role",
        value=_SETTING_DEFAULT_PING_ROLE,
        emoji="🔔",
        description="Pinged for tracked manga without their own role.",
    ),
    discord.SelectOption(
        label="Auto create role for new tracked manhwa",
        value=_SETTING_AUTO_CREATE_ROLE,
        emoji="🪄",
        description="Auto-create a role for each tracked manga.",
    ),
    discord.SelectOption(
        label="Set the bot manager role",
        value=_SETTING_BOT_MANAGER_ROLE,
        emoji="🔧",
        description="Members with this role can use admin commands.",
    ),
    discord.SelectOption(
        label="Set the system notifications channel",
        value=_SETTING_SYSTEM_ALERTS_CHANNEL,
        emoji="❗",
        description="Where critical bot alerts are sent.",
    ),
    discord.SelectOption(
        label="Show buttons for chapter updates",
        value=_SETTING_SHOW_UPDATE_BUTTONS,
        emoji="🔘",
        description="Show 'Mark Read' buttons on update notifications.",
    ),
    discord.SelectOption(
        label="Custom Scanlator Channels",
        value=_SETTING_SCANLATOR_CHANNELS,
        emoji="🗨️",
        description="Route specific websites to dedicated channels.",
    ),
    discord.SelectOption(
        label="Notify for Paid Chapter releases",
        value=_SETTING_PAID_CHAPTER_NOTIFS,
        emoji="💵",
        description="Send notifications for paid / locked chapters.",
    ),
]


class SettingsView(discord.ui.View):
    """Main ephemeral settings view with v1-style menu navigation."""

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
        self._selected_setting: str | None = None
        self._delete_mode = False

        self._main_select: discord.ui.Select = discord.ui.Select(
            placeholder="Select the option to edit.",
            options=_MAIN_OPTIONS,
            min_values=1,
            max_values=1,
            row=0,
        )
        self._main_select.callback = self._on_main_select
        self.add_item(self._main_select)

        self._dynamic_item: discord.ui.Item[Any] | None = None

        save_btn = discord.ui.Button(label="Save", style=discord.ButtonStyle.blurple, row=4)
        save_btn.callback = self._on_save
        self.add_item(save_btn)

        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.blurple, row=4)
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

        delete_mode_btn = discord.ui.Button(
            label="Delete Mode: Off",
            emoji="⚠️",
            style=discord.ButtonStyle.green,
            row=4,
        )
        delete_mode_btn.callback = self._on_delete_mode
        self.add_item(delete_mode_btn)

        delete_config_btn = discord.ui.Button(
            label="Delete config",
            emoji="🗑️",
            style=discord.ButtonStyle.red,
            row=4,
        )
        delete_config_btn.callback = self._on_delete_config
        self.add_item(delete_config_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            return False
        if member.guild_permissions.manage_guild:
            return True
        manager_role_id = self._settings.bot_manager_role_id if self._settings else None
        if manager_role_id and any(r.id == manager_role_id for r in member.roles):
            return True
        await interaction.response.send_message(
            "You need the **Manage Server** permission (or the bot manager role) to use this.",
            ephemeral=True,
        )
        return False

    async def _refresh(self, interaction: discord.Interaction) -> None:
        self._settings = await self._store.get(self._guild_id)
        self._scanlator_overrides = await self._store.list_scanlator_channels(self._guild_id)
        guild = interaction.guild
        me = guild.me if guild else None
        warnings = _collect_warnings(self._settings, guild, me) if guild and me else []
        embed = _build_settings_embed(self._settings, self._scanlator_overrides, warnings)
        await interaction.response.edit_message(embed=embed, view=self)

    def _set_dynamic(self, item: discord.ui.Item[Any] | None) -> None:
        if self._dynamic_item is not None:
            try:
                self.remove_item(self._dynamic_item)
            except ValueError:
                pass
        self._dynamic_item = item
        if item is not None:
            self.add_item(item)

    async def _on_main_select(self, interaction: discord.Interaction) -> None:
        value = self._main_select.values[0]
        self._selected_setting = value

        if value in _CHANNEL_SETTINGS:
            placeholder = (
                "📢 Pick the notifications channel…"
                if value == _SETTING_NOTIFICATIONS_CHANNEL
                else "❗ Pick the system alerts channel…"
            )
            ch_select = discord.ui.ChannelSelect(
                placeholder=placeholder,
                channel_types=[discord.ChannelType.text],
                row=1,
            )
            ch_select.callback = self._on_channel_picked
            self._set_dynamic(ch_select)
        elif value in _ROLE_SETTINGS:
            placeholder = (
                "🔔 Pick the default ping role…"
                if value == _SETTING_DEFAULT_PING_ROLE
                else "🛡️ Pick the bot manager role…"
            )
            role_select = discord.ui.RoleSelect(placeholder=placeholder, row=1)
            role_select.callback = self._on_role_picked
            self._set_dynamic(role_select)
        elif value in _BOOL_SETTINGS:
            current = self._read_bool(value)
            bool_select = discord.ui.Select(
                placeholder="Choose: enable or disable",
                options=[
                    discord.SelectOption(
                        label="Enabled",
                        value="1",
                        emoji="✅",
                        default=current,
                    ),
                    discord.SelectOption(
                        label="Disabled",
                        value="0",
                        emoji="❌",
                        default=not current,
                    ),
                ],
                min_values=1,
                max_values=1,
                row=1,
            )
            bool_select.callback = self._on_bool_picked
            self._set_dynamic(bool_select)
        elif value == _SETTING_SCANLATOR_CHANNELS:
            await self._open_scanlator_channels(interaction)
            return
        else:
            self._set_dynamic(None)

        guild = interaction.guild
        me = guild.me if guild else None
        warnings = _collect_warnings(self._settings, guild, me) if guild and me else []
        embed = _build_settings_embed(self._settings, self._scanlator_overrides, warnings)
        await interaction.response.edit_message(embed=embed, view=self)

    def _read_bool(self, setting: str) -> bool:
        if self._settings is None:
            return setting == _SETTING_SHOW_UPDATE_BUTTONS  # default-on for buttons
        if setting == _SETTING_AUTO_CREATE_ROLE:
            return self._settings.auto_create_role
        if setting == _SETTING_SHOW_UPDATE_BUTTONS:
            return self._settings.show_update_buttons
        if setting == _SETTING_PAID_CHAPTER_NOTIFS:
            return self._settings.paid_chapter_notifs
        return False

    async def _on_channel_picked(self, interaction: discord.Interaction) -> None:
        item = self._dynamic_item
        if not isinstance(item, discord.ui.ChannelSelect):
            await interaction.response.defer()
            return
        channel = item.values[0]
        if self._selected_setting == _SETTING_NOTIFICATIONS_CHANNEL:
            await self._store.set_notifications_channel(self._guild_id, channel.id)
        elif self._selected_setting == _SETTING_SYSTEM_ALERTS_CHANNEL:
            await self._store.set_system_alerts_channel(self._guild_id, channel.id)
        await self._refresh(interaction)

    async def _on_role_picked(self, interaction: discord.Interaction) -> None:
        item = self._dynamic_item
        if not isinstance(item, discord.ui.RoleSelect):
            await interaction.response.defer()
            return
        role = item.values[0]
        guild = interaction.guild
        me = guild.me if guild else None
        if me is not None:
            if role.managed:
                await interaction.response.send_message(
                    f"❌ `{role.name}` is bot-managed and can't be assigned by this bot.",
                    ephemeral=True,
                )
                return
            if role >= me.top_role:
                await interaction.response.send_message(
                    f"❌ `{role.name}` is higher than the bot's top role; pick a lower role.",
                    ephemeral=True,
                )
                return
        if self._selected_setting == _SETTING_DEFAULT_PING_ROLE:
            await self._store.set_default_ping_role(self._guild_id, role.id)
        elif self._selected_setting == _SETTING_BOT_MANAGER_ROLE:
            await self._store.set_bot_manager_role(self._guild_id, role.id)
        await self._refresh(interaction)

    async def _on_bool_picked(self, interaction: discord.Interaction) -> None:
        item = self._dynamic_item
        if not isinstance(item, discord.ui.Select):
            await interaction.response.defer()
            return
        enabled = item.values[0] == "1"
        if self._selected_setting == _SETTING_AUTO_CREATE_ROLE:
            await self._store.set_auto_create_role(self._guild_id, enabled)
        elif self._selected_setting == _SETTING_SHOW_UPDATE_BUTTONS:
            await self._store.set_show_update_buttons(self._guild_id, enabled)
        elif self._selected_setting == _SETTING_PAID_CHAPTER_NOTIFS:
            await self._store.set_paid_chapter_notifs(self._guild_id, enabled)
        await self._refresh(interaction)

    async def _open_scanlator_channels(self, interaction: discord.Interaction) -> None:
        overrides = await self._store.list_scanlator_channels(self._guild_id)
        view = ScanlatorChannelsView(self._bot, self._guild_id, overrides, parent=self)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)

    async def _on_save(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)
        await interaction.followup.send(
            embed=discord.Embed(
                title="Settings Saved",
                description="Your settings have been saved.",
                colour=discord.Colour.green(),
            ),
            ephemeral=True,
        )

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Operation cancelled!",
                description="No changes were made.",
                colour=discord.Colour.red(),
            ),
            view=None,
        )

    async def _on_delete_mode(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._delete_mode = not self._delete_mode
        button.label = f"Delete Mode: {'On' if self._delete_mode else 'Off'}"
        button.style = discord.ButtonStyle.red if self._delete_mode else discord.ButtonStyle.green
        guild = interaction.guild
        me = guild.me if guild else None
        warnings = _collect_warnings(self._settings, guild, me) if guild and me else []
        embed = _build_settings_embed(self._settings, self._scanlator_overrides, warnings)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_delete_config(self, interaction: discord.Interaction) -> None:
        if not self._delete_mode:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Delete Mode is Off",
                    description="Turn on delete mode before deleting the config.",
                    colour=discord.Colour.red(),
                ),
                ephemeral=True,
            )
            return

        pool = getattr(self._store, "_pool", None)
        if pool is not None:
            await pool.execute(
                "DELETE FROM guild_scanlator_channels WHERE guild_id = ?",
                (self._guild_id,),
            )
            await pool.execute(
                "DELETE FROM guild_settings WHERE guild_id = ?",
                (self._guild_id,),
            )
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Config Deleted",
                description="The server config has been deleted.",
                colour=discord.Colour.green(),
            ),
            view=None,
        )


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
            "You need the **Manage Server** permission to use this.", ephemeral=True
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
            "You need the **Manage Server** permission to use this.", ephemeral=True
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


# -- DM settings ----------------------------------------------------------------


def _build_dm_settings_embed(
    paid_chapter_notifs: bool,
    show_update_buttons: bool,
    notifications_enabled: bool,
) -> discord.Embed:
    desc = (
        f"**🔔 DM Notifications:** {_bool_emoji(notifications_enabled)}\n"
        f"​ ​ ​ **^** `Receive personal chapter update DMs from the bot.`\n"
        f"**🔘 Show Update Buttons:** {_bool_emoji(show_update_buttons)}\n"
        f"​ ​ ​ **^** `Show 'Mark Read' buttons on chapter updates in DMs.`\n"
        f"**💰 Paid Chapter Notifs:** {_bool_emoji(paid_chapter_notifs)}\n"
        f"​ ​ ​ **^** `Notify me about premium / locked chapters.`\n"
    )
    return discord.Embed(
        title="DM Settings",
        description=desc,
        colour=discord.Colour.blurple(),
    )


class DmSettingsView(discord.ui.View):
    """Personal DM-context settings view (premium-only)."""

    def __init__(self, bot: Any, user_id: int) -> None:
        super().__init__(timeout=2 * 24 * 60 * 60)
        self._bot = bot
        self._user_id = user_id
        self._store = DmSettingsStore(bot.db)
        self._notifications_enabled = True
        self._paid_chapter_notifs = True
        self._show_update_buttons = True
        self._sync_button_labels()

    async def initialize(self) -> None:
        record = await self._store.get(self._user_id)
        if record is not None:
            self._notifications_enabled = record.notifications_enabled
            self._paid_chapter_notifs = record.paid_chapter_notifs
            self._show_update_buttons = record.show_update_buttons
        self._sync_button_labels()

    def build_embed(self) -> discord.Embed:
        return _build_dm_settings_embed(
            paid_chapter_notifs=self._paid_chapter_notifs,
            show_update_buttons=self._show_update_buttons,
            notifications_enabled=self._notifications_enabled,
        )

    def _sync_button_labels(self) -> None:
        for item in self.children:
            if not isinstance(item, discord.ui.Button):
                continue
            if item.custom_id == "dm_toggle_notifs":
                item.label = f"🔔 DM Notifications: {_bool_emoji(self._notifications_enabled)}"
            elif item.custom_id == "dm_toggle_buttons":
                item.label = f"🔘 Update Buttons: {_bool_emoji(self._show_update_buttons)}"
            elif item.custom_id == "dm_toggle_paid":
                item.label = f"💰 Paid Chapters: {_bool_emoji(self._paid_chapter_notifs)}"

    @discord.ui.button(
        label="🔔 DM Notifications: ✅",
        style=discord.ButtonStyle.secondary,
        custom_id="dm_toggle_notifs",
        row=0,
    )
    async def _toggle_notifs(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._notifications_enabled = not self._notifications_enabled
        await self._store.set_notifications_enabled(self._user_id, self._notifications_enabled)
        self._sync_button_labels()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(
        label="🔘 Update Buttons: ✅",
        style=discord.ButtonStyle.secondary,
        custom_id="dm_toggle_buttons",
        row=0,
    )
    async def _toggle_buttons(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._show_update_buttons = not self._show_update_buttons
        await self._store.set_show_update_buttons(self._user_id, self._show_update_buttons)
        self._sync_button_labels()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(
        label="💰 Paid Chapters: ✅",
        style=discord.ButtonStyle.secondary,
        custom_id="dm_toggle_paid",
        row=0,
    )
    async def _toggle_paid(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self._paid_chapter_notifs = not self._paid_chapter_notifs
        await self._store.set_paid_chapter_notifs(self._user_id, self._paid_chapter_notifs)
        self._sync_button_labels()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
