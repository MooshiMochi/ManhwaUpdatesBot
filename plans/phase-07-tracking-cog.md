# Phase 7 — Tracking cog (`/track new|update|remove|list`)

> **Recommended model:** Claude **Sonnet 4.6** at **medium** reasoning effort.
> The refcount logic across guilds is the only delicate piece; everything
> else is straightforward.

## Goal

Per-guild manga tracking with refcount-aware crawler track/untrack calls.
The bot's tracking table is the single source of truth for which guilds
care about which series; the crawler only sees one tracking record per
series across the whole bot deployment.

## Depends on

- Phase 3 (`db/tracked.py`)
- Phase 4 (bot skeleton)
- Phase 5 (`@has_premium`)
- Phase 6 (autocomplete handlers, formatting helpers)

## Files to create

```
src/manhwa_bot/cogs/tracking.py
```

Append `"manhwa_bot.cogs.tracking"` to `cogs/__init__.py:COGS`.

## Module spec — `cogs/tracking.py`

```python
class TrackingCog(commands.Cog):
    bot: ManhwaBot

    track = app_commands.Group(name="track", description="Manage tracked manga")
```

Permissions on every subcommand:
- `@app_commands.default_permissions(manage_roles=True)`
- `@app_commands.guild_only()` (no DM tracking — tracking is per-guild)
- `@bot_has_permissions(manage_roles=True)` (for /track new role assignment)
- `@checks.has_premium(dm_only=True)` (some tiers grant access)

### `/track new`

Parameters:
- `manga_url: str` — URL of the manga (autocomplete via
  `autocomplete.track_new_url_or_search`)
- `ping_role: discord.Role | None`

Flow:

1. `await interaction.response.defer(ephemeral=False)`.
2. Resolve `manga_url`: if it's a search-result encoded value (contains
   `|`), split into `(website_key, series_url)`. Otherwise, treat as raw
   URL — the crawler's `track_series` will resolve the website from the URL
   pattern.
3. Call `data = await bot.crawler.request("track_series", website_key=..., series_url=...)`.
4. Extract `(website_key, url_name, series_url, series.title, ...)` from the
   response.
5. `await bot.tracked.upsert_series(...)` (writes the master row regardless
   of guild).
6. `await bot.tracked.add_to_guild(guild_id, website_key, url_name, ping_role.id if ping_role else None)`.
7. Build a confirmation embed: title, cover thumbnail, status, "tracked in
   {channel}" if guild_settings.notifications_channel_id is set.
8. Send embed.

Errors:
- Crawler returns `website_disabled`/`website_blocked`/`unknown_type` →
  surface the message in a red embed; don't write to DB.
- Already tracked in this guild → harmless: SQL UPSERT covers it; show
  "already tracked" tip.

### `/track update`

Parameters:
- `manga_id: str` (autocomplete `tracked_manga_in_guild`, value
  `"website_key:url_name"`)
- `role: discord.Role | None` (None means "remove ping role")

Flow:
1. Parse `manga_id` → `(website_key, url_name)`.
2. `await bot.tracked.update_ping_role(guild_id, website_key, url_name, role.id if role else None)`.
3. Confirm via embed.

No crawler call needed.

### `/track remove`

Parameters:
- `manga_id: str` (autocomplete `tracked_manga_in_guild`)
- `delete_role: bool = False`

Flow:
1. Parse `manga_id`.
2. Look up the guild row to capture the `ping_role_id` before deletion.
3. `was_last_guild, remaining = await bot.tracked.remove_from_guild(...)`.
4. If `was_last_guild`: `await bot.crawler.request("untrack_series", website_key=..., url_name=...)`. Then `await bot.tracked.delete_series(...)`.
5. If `delete_role` and the captured role exists: `await role.delete()` (best-effort, swallow `discord.HTTPException`).
6. Confirmation embed showing untracked title + role-deletion outcome.

### `/track list`

No parameters. Pulls every tracked series in this guild via
`bot.tracked.list_for_guild(guild_id, ...)`. Builds paginated embeds
grouped by `website_key`, showing title + URL + ping role mention (if
any). Same `Paginator` from Phase 6.

## Tests

- `test_tracking_refcount_integration.py` — covered partially by
  Phase 3's `test_db_tracked_refcount.py`; here test the cog's
  decision to call `untrack_series` only when `was_last_guild=True`
  using a stub crawler client.

## Verification

```bash
python -m ruff check src/manhwa_bot/cogs/tracking.py
python -m pytest tests/test_tracking_*.py -v
```

Manual against a running crawler + 2 test guilds:
- Track the same series in guild A and guild B.
- `/track remove` in guild A → still tracked, no `untrack_series` call.
- `/track remove` in guild B → bot calls `untrack_series` exactly once;
  master row gone.
- Verify on the crawler side via SQL or `/dev crawler health`.

## Commit message

```
Add tracking cog: /track new|update|remove|list

Refcount-aware: bot calls track_series on the crawler exactly once per
unique (website_key, url_name) regardless of how many guilds are
interested; calls untrack_series only when the last guild removes.
Optional Discord role assignment for per-manga pings.
```
