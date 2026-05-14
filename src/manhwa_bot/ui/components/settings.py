"""Settings cog LayoutView replacements (guild settings + DM settings)."""

from __future__ import annotations

import logging
from typing import Any

import discord

from ...db.dm_settings import DmSettingsStore
from ...db.guild_settings import GuildSettings, GuildSettingsStore
from .. import emojis
from .base import (
    LIST_MAX,
    BaseLayoutView,
    footer_section,
    safe_truncate,
    small_separator,
)

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


def collect_warnings(
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
        warnings.append(
            f"{emojis.ERROR} Bot missing guild permissions: `{', '.join(missing_guild)}`"
        )

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
            warnings.append(f"{emojis.WARNING} {label} not found — it may have been deleted.")
        elif isinstance(ch, discord.TextChannel):
            my_perms = ch.permissions_for(me)
            missing = [
                name.replace("_", " ").title()
                for name, has_it in my_perms
                if getattr(_REQUIRED_CHANNEL_PERMS, name, False) and not has_it
            ]
            if missing:
                warnings.append(
                    f"{emojis.ERROR} Missing permissions in {ch.mention}: "
                    f"`{', '.join(missing)}`"
                )

    for attr, label in (
        ("default_ping_role_id", "Default ping role"),
        ("bot_manager_role_id", "Bot manager role"),
    ):
        role_id = getattr(settings, attr)
        if not role_id:
            continue
        role = guild.get_role(role_id)
        if role is None:
            warnings.append(f"{emojis.WARNING} {label} not found — it may have been deleted.")
        elif role.managed:
            warnings.append(
                f"{emojis.WARNING} {label} is bot-managed and cannot be assigned by this bot."
            )
        elif role >= me.top_role:
            warnings.append(
                f"{emojis.WARNING} {label} is higher than the bot's top role — "
                "the bot can't assign it."
            )

    return warnings


def _bool_emoji(value: bool) -> str:
    return emojis.CHECK if value else emojis.ERROR


def _build_settings_container(
    settings: GuildSettings | None,
    scanlator_overrides: list[dict],
    warnings: list[str],
    *,
    bot: discord.Client | None,
) -> discord.ui.Container:
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
    overrides_text = "\n".join(override_lines) if override_lines else "*None*"

    body = (
        f"**#️⃣ Notifications Channel:** {notif_ch}\n"
        f"-# Chapter update notifications are sent here.\n\n"
        f"**❗ System Alerts Channel:** {alerts_ch}\n"
        f"-# Critical bot alerts are sent here.\n\n"
        f"**🔔 Default Ping Role:** {ping_role}\n"
        f"-# Pinged for chapter updates when a tracked manga has no role of its own.\n\n"
        f"**🛡️ Bot Manager Role:** {manager_role}\n"
        f"-# Members with this role can use admin commands without Manage Server.\n\n"
        f"**🪄 Auto-Create Role:** {auto_create}\n"
        f"-# Automatically create a role when /track new is used without a ping_role.\n\n"
        f"**🔘 Show Update Buttons:** {show_buttons}\n"
        f"-# Show 'Mark Read' buttons on chapter update notifications.\n\n"
        f"**💰 Paid Chapter Notifs:** {paid}\n"
        f"-# Notify subscribers about premium / locked chapters."
    )
    overrides_section = f"**🗨️ Per-Scanlator Channels:**\n{overrides_text}"

    accent = discord.Colour.red() if warnings else discord.Colour.blurple()
    container = discord.ui.Container(
        discord.ui.TextDisplay("# ⚙️  Server Settings"),
        small_separator(),
        discord.ui.TextDisplay(safe_truncate(body, LIST_MAX)),
        small_separator(),
        discord.ui.TextDisplay(overrides_section),
        accent_colour=accent,
    )
    if warnings:
        container.add_item(small_separator())
        container.add_item(
            discord.ui.TextDisplay(f"**{emojis.WARNING} Warnings**\n" + "\n".join(warnings))
        )
    container.add_item(small_separator())
    container.add_item(footer_section(bot))
    return container


# Main-menu setting keys.
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


class SettingsLayoutView(BaseLayoutView):
    """V2 guild-settings panel."""

    def __init__(
        self,
        bot: Any,
        guild_id: int,
        settings: GuildSettings | None,
        scanlator_overrides: list[dict],
    ) -> None:
        super().__init__(invoker_id=None, lock=False, timeout=2 * 24 * 60 * 60)
        self._bot = bot
        self._guild_id = guild_id
        self._store = GuildSettingsStore(bot.db)
        self._settings = settings
        self._scanlator_overrides = scanlator_overrides
        self._selected_setting: str | None = None
        self._delete_mode = False
        self._dynamic_row: discord.ui.ActionRow | None = None
        self._warnings: list[str] = []
        self._rebuild()

    # ---- public ---------------------------------------------------------

    def set_warnings(self, warnings: list[str]) -> None:
        self._warnings = warnings
        self._rebuild()

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

    # ---- rebuild --------------------------------------------------------

    def _rebuild(self) -> None:
        self.clear_items()
        container = _build_settings_container(
            self._settings, self._scanlator_overrides, self._warnings, bot=self._bot
        )
        self.add_item(container)

        # Row: main select
        main_row = discord.ui.ActionRow()
        main_select = discord.ui.Select(
            placeholder="Select the option to edit.",
            options=_MAIN_OPTIONS,
            min_values=1,
            max_values=1,
        )
        main_select.callback = self._on_main_select  # type: ignore[assignment]
        main_row.add_item(main_select)
        self.add_item(main_row)
        self._main_select = main_select

        # Row: dynamic component (placeholder None until a setting is picked)
        if self._dynamic_row is not None:
            self.add_item(self._dynamic_row)

        # Final row: Save / Cancel / Delete Mode / Delete Config
        action_row = discord.ui.ActionRow()
        save_btn = discord.ui.Button(label="Save", style=discord.ButtonStyle.blurple, emoji="💾")
        save_btn.callback = self._on_save  # type: ignore[assignment]
        action_row.add_item(save_btn)

        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.grey)
        cancel_btn.callback = self._on_cancel  # type: ignore[assignment]
        action_row.add_item(cancel_btn)

        delete_mode_btn = discord.ui.Button(
            label=f"Delete Mode: {'On' if self._delete_mode else 'Off'}",
            emoji=emojis.WARNING,
            style=discord.ButtonStyle.red if self._delete_mode else discord.ButtonStyle.green,
        )
        delete_mode_btn.callback = self._on_delete_mode  # type: ignore[assignment]
        action_row.add_item(delete_mode_btn)

        delete_btn = discord.ui.Button(
            label="Delete config", emoji="🗑️", style=discord.ButtonStyle.red
        )
        delete_btn.callback = self._on_delete_config  # type: ignore[assignment]
        action_row.add_item(delete_btn)
        self.add_item(action_row)

    async def _refresh(self, interaction: discord.Interaction) -> None:
        self._settings = await self._store.get(self._guild_id)
        self._scanlator_overrides = await self._store.list_scanlator_channels(self._guild_id)
        guild = interaction.guild
        me = guild.me if guild else None
        self._warnings = collect_warnings(self._settings, guild, me) if guild and me else []
        self._rebuild()
        await interaction.response.edit_message(view=self)

    # ---- main-select callback ------------------------------------------

    def _set_dynamic(self, item: discord.ui.Item[Any] | None) -> None:
        if item is None:
            self._dynamic_row = None
            return
        row = discord.ui.ActionRow()
        row.add_item(item)
        self._dynamic_row = row

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
            )
            ch_select.callback = self._on_channel_picked  # type: ignore[assignment]
            self._set_dynamic(ch_select)
        elif value in _ROLE_SETTINGS:
            placeholder = (
                "🔔 Pick the default ping role…"
                if value == _SETTING_DEFAULT_PING_ROLE
                else "🛡️ Pick the bot manager role…"
            )
            role_select = discord.ui.RoleSelect(placeholder=placeholder)
            role_select.callback = self._on_role_picked  # type: ignore[assignment]
            self._set_dynamic(role_select)
        elif value in _BOOL_SETTINGS:
            current = self._read_bool(value)
            bool_select = discord.ui.Select(
                placeholder="Choose: enable or disable",
                options=[
                    discord.SelectOption(
                        label="Enabled", value="1", emoji=emojis.CHECK, default=current
                    ),
                    discord.SelectOption(
                        label="Disabled", value="0", emoji=emojis.ERROR, default=not current
                    ),
                ],
                min_values=1,
                max_values=1,
            )
            bool_select.callback = self._on_bool_picked  # type: ignore[assignment]
            self._set_dynamic(bool_select)
        elif value == _SETTING_SCANLATOR_CHANNELS:
            await self._open_scanlator_channels(interaction)
            return
        else:
            self._set_dynamic(None)

        guild = interaction.guild
        me = guild.me if guild else None
        self._warnings = collect_warnings(self._settings, guild, me) if guild and me else []
        self._rebuild()
        await interaction.response.edit_message(view=self)

    def _read_bool(self, setting: str) -> bool:
        if self._settings is None:
            return setting == _SETTING_SHOW_UPDATE_BUTTONS
        if setting == _SETTING_AUTO_CREATE_ROLE:
            return self._settings.auto_create_role
        if setting == _SETTING_SHOW_UPDATE_BUTTONS:
            return self._settings.show_update_buttons
        if setting == _SETTING_PAID_CHAPTER_NOTIFS:
            return self._settings.paid_chapter_notifs
        return False

    # ---- dynamic picker callbacks --------------------------------------

    def _current_dynamic_item(self) -> discord.ui.Item[Any] | None:
        if self._dynamic_row is None:
            return None
        children = list(self._dynamic_row.children)
        return children[0] if children else None

    async def _on_channel_picked(self, interaction: discord.Interaction) -> None:
        item = self._current_dynamic_item()
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
        item = self._current_dynamic_item()
        if not isinstance(item, discord.ui.RoleSelect):
            await interaction.response.defer()
            return
        role = item.values[0]
        guild = interaction.guild
        me = guild.me if guild else None
        if me is not None:
            if role.managed:
                await interaction.response.send_message(
                    f"{emojis.ERROR} `{role.name}` is bot-managed and can't be assigned by this bot.",
                    ephemeral=True,
                )
                return
            if role >= me.top_role:
                await interaction.response.send_message(
                    f"{emojis.ERROR} `{role.name}` is higher than the bot's top role; "
                    "pick a lower role.",
                    ephemeral=True,
                )
                return
        if self._selected_setting == _SETTING_DEFAULT_PING_ROLE:
            await self._store.set_default_ping_role(self._guild_id, role.id)
        elif self._selected_setting == _SETTING_BOT_MANAGER_ROLE:
            await self._store.set_bot_manager_role(self._guild_id, role.id)
        await self._refresh(interaction)

    async def _on_bool_picked(self, interaction: discord.Interaction) -> None:
        item = self._current_dynamic_item()
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
        view = ScanlatorChannelsLayoutView(self._bot, self._guild_id, overrides, parent=self)
        await interaction.response.edit_message(view=view)

    async def _on_save(self, interaction: discord.Interaction) -> None:
        # Switch to a small success view inline.
        from .error import build_success_view

        await interaction.response.edit_message(
            view=build_success_view(
                title="Settings saved",
                description="Your settings have been saved.",
                bot=self._bot,
            )
        )

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        from .tracking import build_simple_status_view

        await interaction.response.edit_message(
            view=build_simple_status_view(
                title=f"{emojis.ERROR}  Operation cancelled",
                description="No changes were made.",
                accent=discord.Colour.red(),
                bot=self._bot,
            )
        )

    async def _on_delete_mode(self, interaction: discord.Interaction) -> None:
        self._delete_mode = not self._delete_mode
        guild = interaction.guild
        me = guild.me if guild else None
        self._warnings = collect_warnings(self._settings, guild, me) if guild and me else []
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_delete_config(self, interaction: discord.Interaction) -> None:
        if not self._delete_mode:
            await interaction.response.send_message(
                "Turn on **Delete Mode** before deleting the config.", ephemeral=True
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
        from .error import build_success_view

        await interaction.response.edit_message(
            view=build_success_view(
                title="Config deleted",
                description="The server config has been deleted.",
                bot=self._bot,
            )
        )


# ---------------------------------------------------------------------------
# Scanlator channel overrides sub-view
# ---------------------------------------------------------------------------


class _RemoveButton(discord.ui.Button):
    def __init__(self, parent: ScanlatorChannelsLayoutView, website_key: str) -> None:
        super().__init__(label=f"✕ {website_key}", style=discord.ButtonStyle.danger)
        self._parent = parent
        self._website_key = website_key

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        await self._parent._store.clear_scanlator_channel(self._parent._guild_id, self._website_key)
        overrides = await self._parent._store.list_scanlator_channels(self._parent._guild_id)
        self._parent._overrides = overrides
        self._parent._rebuild()
        await interaction.response.edit_message(view=self._parent)


class ScanlatorChannelsLayoutView(BaseLayoutView):
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        overrides: list[dict],
        *,
        parent: SettingsLayoutView,
    ) -> None:
        super().__init__(invoker_id=None, lock=False, timeout=2 * 24 * 60 * 60)
        self._bot = bot
        self._guild_id = guild_id
        self._overrides = overrides
        self._parent = parent
        self._store = GuildSettingsStore(bot.db)
        self._rebuild()

    def _container(self) -> discord.ui.Container:
        if not self._overrides:
            desc = "*No per-scanlator overrides set.*\nUse **+ Add Override** to add one."
        else:
            lines = [f"• **{r['website_key']}** → <#{r['channel_id']}>" for r in self._overrides]
            desc = "\n".join(lines)
        return discord.ui.Container(
            discord.ui.TextDisplay("## 🗨️  Per-Scanlator Channel Overrides"),
            small_separator(),
            discord.ui.TextDisplay(safe_truncate(desc, LIST_MAX)),
            small_separator(),
            footer_section(self._bot),
            accent_colour=discord.Colour.blurple(),
        )

    def _rebuild(self) -> None:
        self.clear_items()
        self.add_item(self._container())
        # Up to 20 remove buttons across 4 rows of 5.
        if self._overrides:
            for chunk_start in range(0, min(20, len(self._overrides)), 5):
                row = discord.ui.ActionRow()
                for r in self._overrides[chunk_start : chunk_start + 5]:
                    row.add_item(_RemoveButton(self, r["website_key"]))
                self.add_item(row)

        action_row = discord.ui.ActionRow()
        add_btn = discord.ui.Button(
            label="Add Override", emoji="➕", style=discord.ButtonStyle.success
        )
        add_btn.callback = self._on_add_override  # type: ignore[assignment]
        action_row.add_item(add_btn)

        back_btn = discord.ui.Button(label="Back", emoji="↩️", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._on_back  # type: ignore[assignment]
        action_row.add_item(back_btn)
        self.add_item(action_row)

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

        view = ScanlatorAddLayoutView(bot, self._guild_id, keys, parent=self)
        await interaction.response.edit_message(view=view)

    async def _on_back(self, interaction: discord.Interaction) -> None:
        parent = self._parent
        parent._scanlator_overrides = self._overrides
        guild = interaction.guild
        me = guild.me if guild else None
        parent._warnings = collect_warnings(parent._settings, guild, me) if guild and me else []
        parent._rebuild()
        await interaction.response.edit_message(view=parent)


class ScanlatorAddLayoutView(BaseLayoutView):
    """Transient: pick website + channel, then Save."""

    def __init__(
        self,
        bot: Any,
        guild_id: int,
        website_keys: list[str],
        *,
        parent: ScanlatorChannelsLayoutView,
    ) -> None:
        super().__init__(invoker_id=None, lock=False, timeout=300)
        self._bot = bot
        self._guild_id = guild_id
        self._parent = parent
        self._store = GuildSettingsStore(bot.db)
        self._website_keys = website_keys
        self._selected_key: str | None = None
        self._selected_channel_id: int | None = None
        self._rebuild()

    def _status_container(self) -> discord.ui.Container:
        key_text = f"**{self._selected_key}**" if self._selected_key else "*not selected*"
        ch_text = (
            f"<#{self._selected_channel_id}>" if self._selected_channel_id else "*not selected*"
        )
        return discord.ui.Container(
            discord.ui.TextDisplay("## ➕  Add Per-Scanlator Override"),
            small_separator(),
            discord.ui.TextDisplay(
                f"**Website:** {key_text}\n**Channel:** {ch_text}\n\n"
                "Select both, then click **Save**."
            ),
            small_separator(),
            footer_section(self._bot),
            accent_colour=discord.Colour.green(),
        )

    def _rebuild(self) -> None:
        self.clear_items()
        self.add_item(self._status_container())

        key_options = [
            discord.SelectOption(label=k, value=k, default=(k == self._selected_key))
            for k in self._website_keys[:25]
        ]
        key_row = discord.ui.ActionRow()
        key_select = discord.ui.Select(
            placeholder="Select a website / scanlator…", options=key_options
        )
        key_select.callback = self._on_key_selected  # type: ignore[assignment]
        key_row.add_item(key_select)
        self.add_item(key_row)
        self._key_select = key_select

        ch_row = discord.ui.ActionRow()
        ch_select = discord.ui.ChannelSelect(
            placeholder="Select a channel…",
            channel_types=[discord.ChannelType.text],
        )
        ch_select.callback = self._on_channel_selected  # type: ignore[assignment]
        ch_row.add_item(ch_select)
        self.add_item(ch_row)
        self._ch_select = ch_select

        action_row = discord.ui.ActionRow()
        save_btn = discord.ui.Button(label="Save", style=discord.ButtonStyle.success, emoji="💾")
        save_btn.callback = self._on_save  # type: ignore[assignment]
        action_row.add_item(save_btn)
        cancel_btn = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._on_cancel  # type: ignore[assignment]
        action_row.add_item(cancel_btn)
        self.add_item(action_row)

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
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_channel_selected(self, interaction: discord.Interaction) -> None:
        self._selected_channel_id = self._ch_select.values[0].id
        self._rebuild()
        await interaction.response.edit_message(view=self)

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
        self._parent._rebuild()
        await interaction.response.edit_message(view=self._parent)

    async def _on_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=self._parent)


# ---------------------------------------------------------------------------
# DM settings
# ---------------------------------------------------------------------------


class DmSettingsLayoutView(BaseLayoutView):
    def __init__(self, bot: Any, user_id: int) -> None:
        super().__init__(invoker_id=user_id, timeout=2 * 24 * 60 * 60)
        self._bot = bot
        self._user_id = user_id
        self._store = DmSettingsStore(bot.db)
        self._notifications_enabled = True
        self._paid_chapter_notifs = True
        self._show_update_buttons = True

    async def initialize(self) -> None:
        record = await self._store.get(self._user_id)
        if record is not None:
            self._notifications_enabled = record.notifications_enabled
            self._paid_chapter_notifs = record.paid_chapter_notifs
            self._show_update_buttons = record.show_update_buttons
        self._rebuild()

    def _container(self) -> discord.ui.Container:
        body = (
            f"**🔔 DM Notifications:** {_bool_emoji(self._notifications_enabled)}\n"
            "-# Receive personal chapter update DMs from the bot.\n\n"
            f"**🔘 Show Update Buttons:** {_bool_emoji(self._show_update_buttons)}\n"
            "-# Show 'Mark Read' buttons on chapter updates in DMs.\n\n"
            f"**💰 Paid Chapter Notifs:** {_bool_emoji(self._paid_chapter_notifs)}\n"
            "-# Notify me about premium / locked chapters."
        )
        return discord.ui.Container(
            discord.ui.TextDisplay("## ⚙️  DM Settings"),
            small_separator(),
            discord.ui.TextDisplay(body),
            small_separator(),
            footer_section(self._bot),
            accent_colour=discord.Colour.blurple(),
        )

    def _rebuild(self) -> None:
        self.clear_items()
        self.add_item(self._container())

        row = discord.ui.ActionRow()
        notifs_btn = discord.ui.Button(
            label=f"🔔 DM Notifications: {_bool_emoji(self._notifications_enabled)}",
            style=discord.ButtonStyle.secondary,
        )
        notifs_btn.callback = self._toggle_notifs  # type: ignore[assignment]
        row.add_item(notifs_btn)

        buttons_btn = discord.ui.Button(
            label=f"🔘 Update Buttons: {_bool_emoji(self._show_update_buttons)}",
            style=discord.ButtonStyle.secondary,
        )
        buttons_btn.callback = self._toggle_buttons  # type: ignore[assignment]
        row.add_item(buttons_btn)

        paid_btn = discord.ui.Button(
            label=f"💰 Paid Chapters: {_bool_emoji(self._paid_chapter_notifs)}",
            style=discord.ButtonStyle.secondary,
        )
        paid_btn.callback = self._toggle_paid  # type: ignore[assignment]
        row.add_item(paid_btn)
        self.add_item(row)

    async def _toggle_notifs(self, interaction: discord.Interaction) -> None:
        self._notifications_enabled = not self._notifications_enabled
        await self._store.set_notifications_enabled(self._user_id, self._notifications_enabled)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _toggle_buttons(self, interaction: discord.Interaction) -> None:
        self._show_update_buttons = not self._show_update_buttons
        await self._store.set_show_update_buttons(self._user_id, self._show_update_buttons)
        self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _toggle_paid(self, interaction: discord.Interaction) -> None:
        self._paid_chapter_notifs = not self._paid_chapter_notifs
        await self._store.set_paid_chapter_notifs(self._user_id, self._paid_chapter_notifs)
        self._rebuild()
        await interaction.response.edit_message(view=self)
