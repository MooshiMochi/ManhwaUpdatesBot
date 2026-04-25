# Phase 15 — Final verification

> **Recommended model:** Claude **Sonnet 4.6** at **medium** reasoning effort.
> Methodical execution + log inspection; no novel design.

## Goal

End-to-end sanity check before declaring v2 ready. Mirrors the verification
section of the master plan.

## Pre-flight

```bash
cd C:\Users\rchir\Desktop\Local Projects\ManhwaUpdatesBot
git status                       # clean
git log --oneline | head -20     # phase 1..14 commits visible
```

## Static checks

```bash
python -m ruff check .
python -m ruff format --check .
```

Both must be clean.

## Unit tests

```bash
python -m pytest -v
```

All green. No skipped tests except those explicitly marked `requires_discord`
or `requires_crawler` (live tests).

## Local crawler integration

In one terminal:

```bash
cd "C:\Users\rchir\Desktop\Local Projects\crawler_backend"
python main.py
```

In another:

```bash
cd "C:\Users\rchir\Desktop\Local Projects\crawler_backend"
python -m src.scripts.create_api_key --name manhwa-bot
# copy the token
```

Wire the token into `ManhwaUpdatesBot/.env` as `CRAWLER_API_KEY=...`.
Fill `DISCORD_BOT_TOKEN` from the Developer Portal. Optional:
`PATREON_ACCESS_TOKEN`.

In a third terminal:

```bash
cd "C:\Users\rchir\Desktop\Local Projects\ManhwaUpdatesBot"
python main.py
```

Bot logs should show:
- `loaded N cogs`
- `connected to crawler at ws://...`
- `catch-up complete, last_acked=...`
- `logged in as <bot>`

## Smoke tests in a test guild

Owner home guild only. Run:

| Command | Expected |
|---|---|
| `@bot d sync ~` | Slash commands appear in this guild. |
| `/supported_websites` | List matches the crawler's. |
| `/search query:demon slayer` | Real results. |
| `/track new manga_url:<a real URL>` | Confirmation embed; series in DB. |
| `/info series_id:<auto-completed>` | Embed with cover. |
| `/chapters series_id:<...>` | Paginated chapters. |
| `/bookmark new` | Persists. |
| `/bookmark view` | BookmarkView opens. |
| `/settings` | SettingsView; pick channel; persists. |
| `/subscribe new manga_id:<...>` | Persists. |
| `/stats` | Counts. |
| `/translate text:Bonjour` | "Hello". |
| Right-click message → Translate | Embed. |
| `@bot d crawler health` | Table. |
| `@bot d premium grant user <self> 1h` | Row inserted. |
| `@bot d premium check <@self>` | Source = grant_user. |

## Push event end-to-end

In the crawler's Python REPL or a one-off script:

```python
from src.services.container import create_services
from src.config import load_config
import asyncio
async def main():
    cfg = load_config()
    services = await create_services(cfg)
    await services.notifications.publish_new_chapters(
        website_key="<some_key>",
        url_name="<some_url_name>",
        series_title="Smoke Test",
        chapters=[{"index": 99, "name": "Chapter 99", "url": "https://example.com", "is_premium": False}],
    )
asyncio.run(main())
```

(Adjust to actual API.) Within ~1s, the bot posts a chapter-update embed
in the configured notifications channel and DMs subscribed users.

## Catch-up replay

1. Stop the bot (Ctrl+C).
2. Trigger another `publish_new_chapters` on the crawler.
3. Restart the bot.
4. Within ~5s, the missed notification posts. Bot logs show
   `catch-up replayed 1 record`.

## Refcount

1. Track the same series in two test guilds.
2. `/track remove` in guild A — series stays tracked on the crawler
   (verify via `@bot d crawler health` or by hitting the crawler's
   `notifications` API directly).
3. `/track remove` in guild B — bot calls `untrack_series`; verify on
   crawler the row is gone.

## Premium across all sources

| Setup | Expected `is_premium` source |
|---|---|
| No grant, no Patreon, no entitlement | `(False, None)` |
| `@bot d premium grant user <self> 1h` | `grant_user` |
| Revoke; link Patreon (real subscription) → `@bot d premium patreon refresh` | `patreon` |
| Issue Discord Test Entitlement against a configured user SKU | `discord_user` |
| Owner with `owner_bypass=true` | `owner` |
| Disable `[premium] enabled=false` | `disabled` |

## Intent assertion

Random message in a channel without mentioning the bot: the bot must NOT
respond. `@bot d sync ~` must work. This proves `message_content=False`
and mention-based content delivery.

## Sign-off

Open a PR or commit a `RELEASE.md` summarizing:
- v2.0 ships.
- All 15 phases land.
- Manual verification passed.
- v1 archived on the `v1` branch; users can roll back via
  `git checkout v1`.

## Commit message (for any final fixes)

```
Verify v2.0 end-to-end and capture release notes

All static checks, unit tests, and live integration smoke tests pass
against a local crawler instance. v2.0 is ready to ship.
```
