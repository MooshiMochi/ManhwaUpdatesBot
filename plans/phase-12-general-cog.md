# Phase 12 — General cog (`/help`, `/stats`, `/get_lost_manga`, `/patreon`, `/next_update_check`, `/translate`, context menus)

> **Recommended model:** Claude **Sonnet 4.6** at **medium** reasoning effort.
> A grab-bag of mostly self-contained commands; `/translate` is the only
> non-trivial piece (Google Translate API integration).

## Goal

The catch-all cog: help text, stats, lost-manga export, Patreon link,
next-update-check info, message translation. Nothing here calls the
crawler except `/get_lost_manga` (uses `supported_websites`).

## Depends on

- Phase 3 (`db/*` for `/stats`)
- Phase 6 (`bot.websites_cache` for `/get_lost_manga`)

## Files

```
src/manhwa_bot/cogs/general.py
src/manhwa_bot/i18n/google_translate.py     # thin async client
tests/test_lost_manga_export.py
```

Append `"manhwa_bot.cogs.general"` to `COGS`.

## Module specs

### `i18n/google_translate.py`

aiohttp-based client for Google Translate's free endpoint
(`https://translate.googleapis.com/translate_a/single`). v1 used the same
unofficial endpoint — preserve compatibility. If you want a paid API key,
expose a config slot but default to the free endpoint.

```python
async def translate(
    text: str,
    *,
    target: str = "en",
    source: str = "auto",
    session: aiohttp.ClientSession,
) -> tuple[str, str]:
    """Returns (translated_text, detected_source_language)."""
```

Cache the language-list response for the autocomplete handler.

### `cogs/general.py`

```python
class GeneralCog(commands.Cog):
    bot: ManhwaBot
```

#### `/help`
- Static embed listing command groups with one-line descriptions.
- No premium gate.

#### `/stats`
- Counts: bookmarks, tracked series (master count), guild count, user
  count (`bot.users` length is a rough estimate; v1 used a DB count of
  unique subscribers).
- Uptime: `datetime.utcnow() - bot.started_at`.
- No premium gate.

#### `/get_lost_manga`
- `supported = set(await bot.websites_cache.get_or_set(...))` — current
  crawler-supported websites.
- Pull every distinct `website_key` from `tracked_series` and `bookmarks`.
- Difference = unsupported (lost) website keys. Pull rows where
  `website_key` is in that set.
- Emit a TSV: `tab-separated columns: kind (tracked/bookmark), website_key,
  url_name, title, series_url, last_read_chapter (for bookmarks)`.
- Send as `discord.File` attached to a small embed: "N entries from M lost
  websites".

#### `/search` — already in catalog cog (skip here).

#### `/translate text [to] [from_]`
- `to: str = "en"` (autocomplete from cached language list)
- `from_: str = "auto"`
- Calls `google_translate.translate(...)`.
- Embed shows source language (detected if "auto"), target language,
  original text, translation. Truncate to 4096 chars.

#### `/patreon`
- Static embed with Patreon link + tier descriptions.
- The Patreon URL comes from `config.premium.patreon.pledge_url` if set,
  else hard-code to https://www.patreon.com/<user>'s preference (read
  from a static `[bot] patreon_url` config slot — add this to the example
  config in this phase).

#### `/next_update_check show_all`
- The crawler controls the schedule and doesn't expose it via WS in v1
  of this plan. Embed reads: "Updates run automatically — typical cadence
  is 25 minutes between checks. The bot doesn't track the schedule
  directly anymore." If `show_all` is true, list `bot.websites_cache`
  contents but with no per-site times.

  (Future: add a crawler op `next_check_times` and consume it here.)

#### Context menus

- `Translate` (`@app_commands.context_menu(name="Translate")`):
  - Param: `message: discord.Message`
  - Translates `message.content` to English.
- `Translate to…`:
  - Opens a modal asking for target language.
  - Calls translate with that target.

Both gated by `@checks.has_premium(dm_only=True)`.

## Tests

- `test_lost_manga_export.py` — set up: tracked rows from website "alive"
  and "dead"; `bot.websites_cache` returns `["alive"]`. Run export →
  TSV contains only "dead" rows.

## Verification

```bash
python -m ruff check src/manhwa_bot/cogs/general.py src/manhwa_bot/i18n
python -m pytest tests/test_lost_manga_export.py -v
```

Manual:
- `/help` displays.
- `/stats` shows counts.
- `/translate text:Bonjour` returns "Hello".
- Right-click message → "Translate" → embed.

## Commit message

```
Add general cog: /help, /stats, /get_lost_manga, /patreon,
/next_update_check, /translate, and Translate context menus

Free-tier-friendly: only /get_lost_manga touches the crawler (for the
supported_websites diff). /translate uses the unofficial Google
Translate endpoint (matches v1).
```
