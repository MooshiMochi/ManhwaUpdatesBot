# Phase 9 — Bookmarks cog (`/bookmark new|view|update|delete` + BookmarkView)

> **Recommended model:** Claude **Sonnet 4.6** at **medium** reasoning effort.
> The auto-subscribe-on-final-chapter path and the BookmarkView UI need
> care.

## Goal

User-managed bookmarks with folders and last-read tracking. Mirrors v1's
behavior (folder set: `Reading`, `On Hold`, `Plan to Read`, `Re-Reading`,
`Completed`, `Dropped`). Auto-subscribes the user when they reach the last
chapter of an ongoing series.

## Depends on

- Phase 3 (`db/bookmarks.py`)
- Phase 6 (Paginator, autocomplete `user_bookmarks`, formatting)
- Phase 8 (`subscribe_user` via `bot.subs`)
- Crawler op `chapters` (for resolving last_read_chapter on `/bookmark new`)

## Reference v1 behavior

Read these from the `v1` branch for parity:

```bash
cd ManhwaUpdatesBot
git show v1:src/ext/bookmark.py | less
git show v1:src/ui/bookmark_view.py | less    # actual path may differ
git show v1:src/core/objects.py | less        # Bookmark dataclass
```

Mirror the view modes (visual + text) and folder-filter dropdown.

## Files

```
src/manhwa_bot/cogs/bookmarks.py
src/manhwa_bot/ui/bookmark_view.py
tests/test_bookmark_auto_subscribe.py
```

Append `"manhwa_bot.cogs.bookmarks"` to `COGS`.

## Module specs

### `ui/bookmark_view.py` — `BookmarkView`

Sub-classes `discord.ui.View`. Rendered by `/bookmark view`.

State:
- `bookmarks: list[Bookmark]` (filtered to currently shown folder)
- `current_folder: str | None` (None = all folders)
- `index: int` (which bookmark is shown)
- `mode: Literal["visual", "text"]`

Components:
- `discord.ui.Select` for folder filter (options: All, Reading, On Hold, ...)
- Prev / Next bookmark buttons
- "Toggle view mode" button (visual ↔ text)
- "Jump to series" link button (to the manga URL)
- "Set last read" button → opens a modal taking a chapter index, then calls
  `bookmarks.update_last_read` and refreshes.

Visual mode: large embed with cover thumbnail, title, last-read chapter,
folder, link.
Text mode: list-style embed showing 10 bookmarks per page with title +
folder + last-read.

`interaction_check` ensures only the original user can interact.

### `cogs/bookmarks.py`

```python
class BookmarksCog(commands.Cog):
    bookmark = app_commands.Group(name="bookmark", description="Track your reading progress")
```

All commands `@checks.has_premium(dm_only=True)`.

#### `/bookmark new manga_url_or_id [folder=Reading]`
1. Resolve `manga_url_or_id` to `(website_key, series_url)` by either:
   - Splitting `"website_key:url_name"` (autocomplete value), then we already
     have `url_name`; fetch series_url from `tracked_series` if known, else
     call `crawler.request("info", ...)` to canonicalize.
   - Treating as URL.
2. Call `crawler.request("chapters", website_key=..., url=series_url)`.
3. If chapters list is empty → red embed "no chapters available".
4. Initialize `last_read_chapter` to `chapters[0].text` and `last_read_index = 0`.
5. `await bot.bookmarks.upsert_bookmark(user_id, website_key, url_name,
   folder=folder, last_read_chapter=..., last_read_index=0)`.
6. Confirmation embed.

#### `/bookmark view [series_id] [folder]`
- Loads `bot.bookmarks.list_user_bookmarks(user_id, folder=folder)`.
- Filters to only series whose `website_key` is currently supported (via
  `bot.websites_cache`); silently drops unsupported (visible in
  `/get_lost_manga`).
- If `series_id` provided, jumps the view's index to that bookmark.
- Sends a `BookmarkView`.

#### `/bookmark update series_id [chapter_index] [folder]`
1. Require at least one of `chapter_index` / `folder`.
2. Resolve `(website_key, url_name)` from `series_id`.
3. Look up bookmark; error if absent.
4. If `chapter_index` provided:
   - `chapters = await crawler.request("chapters", ...)`.
   - Validate index is in range.
   - `await bot.bookmarks.update_last_read(... chapter_text=chapters[idx].text, chapter_index=idx)`.
   - **Auto-subscribe path**: if `idx == len(chapters) - 1` AND series is
     not in a "completed" status (look up via `tracked_series.status` if
     present, else inspect crawler `info`), AND tracked in this guild,
     AND user not already subscribed → call `bot.subs.subscribe(...)` and
     append "auto-subscribed for new chapters" to the confirmation.
     If not tracked: append "ask a server admin to /track this series".
5. If `folder` provided: `update_folder(...)`.
6. Confirmation embed.

#### `/bookmark delete series_id`
- Resolves and `bot.bookmarks.delete_bookmark(...)`. Confirms.

## Tests

- `test_bookmark_auto_subscribe.py` — stub the crawler client + bookmark
  store. Set up: tracked in guild, user has bookmark at index N-2, series
  ongoing. Update to index N-1 → assert `subscribe()` called. Re-update
  with same index → no second subscribe call (idempotent).
- BookmarkView UI tests skipped (covered by manual).

## Verification

```bash
python -m ruff check src/manhwa_bot/cogs/bookmarks.py src/manhwa_bot/ui/bookmark_view.py
python -m pytest tests/test_bookmark_*.py -v
```

Manual:
- `/bookmark new` against a tracked series → embed.
- `/bookmark view` → BookmarkView with folder filter.
- Reach last chapter → confirmation includes auto-subscribe note.
- `/bookmark update` to a non-final chapter → no auto-subscribe.

## Commit message

```
Add bookmarks cog: /bookmark new|view|update|delete + BookmarkView

Folder-aware (Reading / On Hold / Plan to Read / Re-Reading / Completed
/ Dropped). Auto-subscribes the user to the series when they update
last-read to the final chapter of an ongoing tracked manga (mirrors v1).
```
