# Phase 8 — Subscriptions cog (`/subscribe new|delete|list`)

> **Recommended model:** Claude **Haiku 4.5** at **low** reasoning effort.
> Pure DB work; smallest cog. Haiku is fast enough and saves cost.

## Goal

User-level subscriptions to tracked series for DM notifications. No crawler
calls — the bot already receives every notification (because the bot's API
key tracks every series), and the bot decides per-user whether to DM based
on these subscription rows.

## Depends on

- Phase 3 (`db/subscriptions.py`)
- Phase 4 (bot skeleton)
- Phase 5 (`@has_premium`)
- Phase 6 (Paginator, autocomplete handlers)

## Files

```
src/manhwa_bot/cogs/subscriptions.py
```

Append `"manhwa_bot.cogs.subscriptions"` to `COGS`.

## Module spec

```python
class SubscriptionsCog(commands.Cog):
    subscribe = app_commands.Group(name="subscribe", description="Manage notifications for manga")
```

### `/subscribe new`
- `manga_id: str` (autocomplete `tracked_manga_in_guild` — only show series
  this guild tracks; otherwise users could subscribe to nothing).
- Parses to `(website_key, url_name)`. Verifies it's tracked in this guild
  (defensive — autocomplete already filters). If not, returns "not tracked
  here" embed.
- `await bot.subs.subscribe(user_id=..., guild_id=..., website_key=..., url_name=...)`.
- Confirm via embed showing title + the channel where notifications will be
  posted (`guild_settings.notifications_channel_id`) plus "and via DM" if
  the user has DMs enabled in `dm_settings`.

Special form: `manga_id == "*"` (or a "Subscribe to all" option) →
batch-subscribe to every series the guild tracks the user isn't already
subscribed to.

### `/subscribe delete`
- `manga_id: str` (autocomplete `user_subscribed_manga`)
- `await bot.subs.unsubscribe(...)`.
- Same `*` special form for "unsubscribe all".

### `/subscribe list`
- `_global: bool = False` — if true, include subs across all guilds.
- Pulls via `subs.list_for_user(...)` with optional `guild_id` filter.
- Paginated embed grouped by guild (when `_global=True`) or website key.

All commands `@checks.has_premium(dm_only=True)`.

## Verification

```bash
python -m ruff check src/manhwa_bot/cogs/subscriptions.py
```

Manual:
- `/subscribe new manga_id:<one of guild's tracked>` → confirms.
- `/subscribe list` shows it.
- `/subscribe delete manga_id:<...>` removes; list is empty.

## Commit message

```
Add subscriptions cog: /subscribe new|delete|list

Pure local DB. The bot's single API key receives every notification;
this cog decides per-user whether to DM. Supports a "*" wildcard for
batch (un)subscribe.
```
