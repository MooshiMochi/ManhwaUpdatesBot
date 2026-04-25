# Phase 6 — Catalog cog (`/search`, `/info`, `/chapters`, `/supported_websites`)

> **Recommended model:** Claude **Sonnet 4.6** at **medium** reasoning effort.
> Mostly thin passthroughs to the crawler client; pagination is the only
> notable wrinkle.

## Goal

First user-facing cog. Exercises the crawler client end-to-end. After this
phase, the bot can search, fetch info, and list chapters — even though
nothing is tracked yet.

## Depends on

- Phase 4 (bot skeleton, cog registry)
- Phase 5 (`@has_premium` decorator)
- Crawler ops: `search`, `info`, `chapters`, `supported_websites`,
  `download_cover` (master plan: "Crawler API surface" table).

## Files to create

```
src/manhwa_bot/cogs/catalog.py
src/manhwa_bot/ui/paginator.py
src/manhwa_bot/ui/subscribe_view.py
src/manhwa_bot/autocomplete.py
src/manhwa_bot/formatting.py
src/manhwa_bot/cache.py             # supported_websites TTL cache
tests/
├── test_paginator.py
└── test_supported_websites_cache.py
```

Append `"manhwa_bot.cogs.catalog"` to `cogs/__init__.py:COGS`.

## Module specs

### `cache.py`

`class TtlCache[V]` with `get_or_set(key, loader, ttl_seconds)` and `invalidate(key)`. Used for the `supported_websites` cache (60-min TTL by default per config).

### `formatting.py`

Pure functions, no side effects:

- `series_info_embed(data, *, request_id) -> discord.Embed` — title, status, synopsis (truncated to 4096), cover URL via `embed.set_thumbnail`. Footer shows website key + request id (small).
- `chapter_list_embeds(chapters, *, page_size=15) -> list[discord.Embed]` — splits chapters into pages.
- `search_results_embed(results, *, query, page) -> discord.Embed` — one embed per page; up to 5 results per page; each result has title, website, link.
- `failed_websites_field(failed) -> tuple[str, str] | None` — for inclusion in search embeds.

### `ui/paginator.py`

`class Paginator(discord.ui.View)` with First / Prev / Page X/Y / Next / Last buttons. Constructed with a list of embeds (or a callable that yields them). 5-minute interaction timeout. `interaction_check` ensures only the original invoker can navigate (configurable).

Tested in `test_paginator.py`: page math (clamp at edges), button states (disabled at boundaries).

### `ui/subscribe_view.py`

`class SubscribeView(discord.ui.View)` rendered on top of search-result and info embeds. One button: "Subscribe to updates" — invokes `subscriptions.subscribe(user_id, guild_id, website_key, url_name)` directly (uses the bot's stores; doesn't go through a slash command). Shows a confirmation toast.

For `/info`: also a "Track in this server" button (only visible/enabled if invoker has `manage_roles` permission), routes to the same code path as `/track new`.

### `autocomplete.py`

App-command autocomplete handlers:

- `tracked_manga_in_guild(interaction, current) -> list[Choice]` — pulls from `tracked_in_guild` joined to `tracked_series` for the invoker's guild. Choice value format: `"{website_key}:{url_name}"`. Choice name: `"{title} ({website_key})"`. Limit 25 (Discord cap), filtered by `current` substring.
- `user_subscribed_manga(interaction, current)` — pulls from `subscriptions` for the user.
- `user_bookmarks(interaction, current)` — pulls from `bookmarks` for the user.
- `supported_website_keys(interaction, current)` — calls `bot.websites_cache.get_or_set(...)` to get the crawler list; returns the keys.
- `track_new_url_or_search(interaction, current)` — when typing a URL, returns the URL itself; otherwise runs `crawler.request("search", query=current, limit=10)` and returns up to 10 results encoded as `"{website_key}|{series_url}"` so the resolver later canonicalizes.

All autocompletes return `[]` on errors (never raise from autocomplete — Discord shows "no choices").

### `cogs/catalog.py`

```python
class CatalogCog(commands.Cog):
    bot: ManhwaBot

    @app_commands.command(name="search", description="Search for a manga")
    @app_commands.describe(query="Title or URL", scanlator_website="Restrict to one website")
    @app_commands.autocomplete(scanlator_website=autocomplete.supported_website_keys)
    @checks.has_premium(dm_only=True)
    async def search(self, interaction, query: str, scanlator_website: str | None = None):
        ...
```

Implementations:

- **`/search query [scanlator_website]`**:
  - `await interaction.response.defer(thinking=True)`.
  - `data = await bot.crawler.request("search", query=query, website_key=scanlator_website, limit=20, timeout_ms=15000)`.
  - Build paginated embeds via `formatting.search_results_embed`.
  - `await interaction.followup.send(embed=..., view=SubscribeView(...))` for the first page; the `Paginator` re-renders the subscribe view per page.

- **`/info series_id`**: `series_id` is the autocomplete value `"website_key:url_name"` OR a direct URL. Resolve to `(website_key, series_url)`; call `crawler.request("info", website_key=..., url=...)`. Send `series_info_embed` + `SubscribeView`.

- **`/chapters series_id`**: same resolution; call `crawler.request("chapters", website_key=..., url=...)`. Paginate with 15 chapters per page.

- **`/supported_websites`**: call `bot.websites_cache.get_or_set(...)` (crawler `supported_websites` op). Render as a paginated embed with website keys; one row per website.

### Bot wiring

In `bot.setup_hook` add (after services are built):

```python
self.websites_cache: TtlCache[list[str]] = TtlCache()
```

## Tests

- `test_paginator.py` — page bounds, button states.
- `test_supported_websites_cache.py` — first call hits the loader; second within TTL doesn't; after TTL it does.

(End-to-end command tests require a running Discord — covered by manual
verification.)

## Verification

```bash
python -m ruff check src/manhwa_bot/cogs/catalog.py src/manhwa_bot/ui src/manhwa_bot/autocomplete.py src/manhwa_bot/formatting.py src/manhwa_bot/cache.py
python -m pytest tests/test_paginator.py tests/test_supported_websites_cache.py -v
```

Manual against a running crawler + test guild:
- `/supported_websites` → list matches `crawler_backend` `python -m src.scripts...`
- `/search query:demon slayer` → at least one result.
- `/info series_id:<autocomplete pick>` → embed with title + cover.
- `/chapters series_id:<...>` → paginated chapter list.

## Commit message

```
Add catalog cog: /search, /info, /chapters, /supported_websites

- Generic Paginator view with first/prev/next/last
- SubscribeView attached to search results and info embeds
- Autocomplete handlers for tracked manga, user subs, user bookmarks,
  website keys, and search-as-you-type for /track
- TTL cache for supported_websites (60-min default)
- Embed builders in formatting.py
```
