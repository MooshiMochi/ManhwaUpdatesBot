# Phase 10 — Settings cog (`/settings` + SettingsView)

> **Recommended model:** Claude **Sonnet 4.6** at **medium** reasoning effort.
> The view is the only complex piece; bigger than `/subscribe` but smaller
> than bookmarks.

## Goal

Per-guild configuration UI: notifications channel, system alerts channel,
default ping role, paid-chapter toggle, optional per-scanlator channel
overrides. Mirrors v1's `SettingsView`.

## Depends on

- Phase 3 (`db/guild_settings.py`, `db/dm_settings.py`)
- Phase 4 (bot skeleton)

## Reference v1 behavior

```bash
git show v1:src/ext/config.py | less
git show v1:src/ui/settings_view.py | less     # actual path may differ
```

Replicate the SettingsView layout: ephemeral message with channel/role
selectors and toggle buttons.

## Files

```
src/manhwa_bot/cogs/settings.py
src/manhwa_bot/ui/settings_view.py
```

Append `"manhwa_bot.cogs.settings"` to `COGS`.

## Module specs

### `ui/settings_view.py` — `SettingsView`

Components (all in one ephemeral message):

- `discord.ui.ChannelSelect` (text channels only) for **Notifications channel** — saves to `guild_settings.notifications_channel_id`.
- `discord.ui.ChannelSelect` for **System alerts channel** — saves to `guild_settings.system_alerts_channel_id`.
- `discord.ui.RoleSelect` for **Default ping role** — saves to `guild_settings.default_ping_role_id`.
- `discord.ui.Button` (toggle) for **Paid chapter notifications** — flips `guild_settings.paid_chapter_notifs`.
- `discord.ui.Button` for **Per-scanlator channels…** — opens a sub-view
  (or modal-driven flow) for `guild_scanlator_channels` overrides.

`interaction_check` requires `manage_guild=True` permission.

Re-renders the embed on every change with the current values (resolved to
mentions: `<#channel>`, `<@&role>`, ✅/❌).

The sub-view for per-scanlator overrides:
- Lists current overrides with a "remove" button each.
- A "+ Add override" button opens a modal: select a website key (from a
  `discord.ui.Select` populated via `bot.websites_cache`) and a channel.

### `cogs/settings.py`

```python
class SettingsCog(commands.Cog):
    @app_commands.command(name="settings", description="Configure bot settings for this server")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @checks.has_permissions(manage_guild=True, is_bot_manager=True)  # bot-side gate
    @checks.bot_has_permissions(send_messages=True, embed_links=True)
    async def settings(self, interaction):
        await interaction.response.send_message(
            embed=settings_embed(...),
            view=SettingsView(...),
            ephemeral=True,
        )
```

Note the system reminder in v1: bot must have `manage_roles + send_messages + embed_links + attach_files + use_external_emojis` to function fully — the view runs a permission audit and prepends warnings if any are missing.

`/settings` does NOT require `@has_premium`.

## Verification

```bash
python -m ruff check src/manhwa_bot/cogs/settings.py src/manhwa_bot/ui/settings_view.py
```

Manual:
- `/settings` opens the ephemeral view.
- Pick a channel → bot updates DB and re-renders embed showing the choice.
- Toggle paid-chapter button → state flips and persists.
- Add a per-scanlator override → it appears in the list.

## Commit message

```
Add settings cog: /settings + SettingsView

Ephemeral guild config UI: notifications channel, system alerts channel,
default ping role, paid-chapter toggle, per-scanlator channel overrides.
Permission audit warns if the bot is missing channel-level permissions
needed for notifications.
```
