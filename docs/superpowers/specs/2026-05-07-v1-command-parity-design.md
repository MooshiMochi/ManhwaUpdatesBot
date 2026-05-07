# V1 Command Parity Design

## Goal

Recreate the Discord-facing slash command UI, views, components, response style, and user flows from `ManhwaUpdatesBot-v1` in `ManhwaUpdatesBot` v2 while keeping v2's crawler-backed architecture. From a Discord user's point of view, supported commands should behave like v1 unless the crawler backend makes an exact match impossible.

`/get_lost_manga` is intentionally out of scope for this parity pass. Leave the current v2 command registered and unchanged because it will be used later for removed-website migration work.

## Context

V1 concentrates slash commands in:

- `src/ext/commands.py`
- `src/ext/bookmark.py`
- `src/ext/config.py`
- shared UI in `src/ui/views.py`, `src/ui/selects.py`, `src/ui/buttons.py`, and `src/ui/modals.py`

V2 splits equivalent behavior across:

- `src/manhwa_bot/cogs/tracking.py`
- `src/manhwa_bot/cogs/subscriptions.py`
- `src/manhwa_bot/cogs/bookmarks.py`
- `src/manhwa_bot/cogs/catalog.py`
- `src/manhwa_bot/cogs/general.py`
- `src/manhwa_bot/cogs/settings.py`
- shared UI in `src/manhwa_bot/ui/*`
- embed helpers in `src/manhwa_bot/formatting.py`

V2 already has most crawler-backed command implementations, but its public command metadata, component labels, button styles, pagination behavior, bookmark browser, search action flow, and settings flow have diverged from v1.

## Non-Goals

- Do not remove, rewrite, or redesign `/get_lost_manga`.
- Do not reintroduce v1's direct scanlator scraping into v2.
- Do not replace v2's crawler service, database stores, migration model, or premium service.
- Do not attempt a data migration from v1's SQLite schema as part of this UI parity pass.
- Do not redesign the user experience beyond restoring v1 behavior.

## Recommended Approach

Use a v1 UX compatibility layer in v2.

Keep v2's crawler-backed stores and request flows, but restore v1's Discord-facing surface by adapting command metadata, embed builders, paginator behavior, action views, bookmark view, confirmation prompts, and settings components. This avoids the risk of directly copying v1 UI code that depends on v1 scanlator classes, old DB objects, and direct scraping APIs.

## Command Surface Parity

Update v2 command names, descriptions, option descriptions, and displayed option names to match v1 where Discord exposes them.

Commands to align:

- `/next_update_check`
  - Description: `Get the time of the next update check.`
  - Option `show_all`: `Whether to show the next update check for all scanlators supported by the bot.`
- `/track`
  - Group description: `(Mods) Start tracking a manga for the server to get notifications.`
  - `/track new`: `Start tracking a manga for the server to get notifications.`
  - `/track update`: `Update a tracked manga for the server to get notifications.`
  - `/track remove`: `Stop tracking a manga on this server.`
  - `/track list`: `List all the manga that are being tracked in this server.`
  - Display option names should include `manga` for tracked manga selections.
- `/subscribe`
  - Group description: `Subscribe to a manga to get notifications.`
  - `/subscribe new`: `Subscribe to a tracked manga to get new release notifications.`
  - `/subscribe delete`: `Unsubscribe from a currently subscribed manga.`
  - `/subscribe list`: `List all the manga you're subscribed to.`
  - Display option names should include `manga` and `global`.
- `/bookmark`
  - Group description: `Bookmark a manga`
  - `/bookmark new`: `Bookmark a new manga`
  - `/bookmark view`: `View your bookmark(s)`
  - `/bookmark update`: `Update a bookmark`
  - `/bookmark delete`: `Delete a bookmark`
  - Display option names should include `manga_url`, `manga`, and `chapter`.
- `/chapters`
  - Description: `Get a list of chapters for a manga.`
  - Display option name: `manga`.
- `/supported_websites`
  - Description: `Get a list of supported websites.`
- `/help`
  - Already aligned; keep v1 embed and support buttons.
- `/info`
  - Description: `Display info about a manhwa.`
  - Display option name: `manhwa`.
- `/search`
  - Description: `Search for a manga on on all/one scanlator of choice.`
  - Display option name: `scanlator`.
- `/translate`
  - Description: `Translate any text from one language to another`
  - Display option name: `from`.
- `/stats`
  - Description: `Get some basic info and stats about the bot.`
- `/patreon`
  - Description: `Help fund the server and manage your current patreon subscription`
- `/settings`
  - Description: `View and Edit the server/DM settings.`

Keep v2's developer prefix commands and crawler/premium developer commands out of this slash-command parity scope.

## Interaction And View Parity

### Paginator

Restore v1 navigation behavior for shared paginated embed views:

- Row 0 buttons in this order: `⏮️`, `⬅️`, `⏹️`, `➡️`, `⏭️`.
- Button styles: blurple for navigation, red for stop.
- Previous and next wrap around at boundaries.
- Stop removes the navigation view from the message and stops the view.
- Unauthorized users receive the v1-style red embed title `🚫 You cannot use this menu!`.
- Long-lived v1-style timeout behavior should be preserved for views that had multi-hour or multi-day timeouts.

The implementation can extend the current `Paginator` class or add a `V1Paginator` wrapper, as long as command call sites use the v1 behavior where users can see it.

### Confirm View

Restore v1 confirmation prompts:

- Buttons: `Confirm` green, `Cancel` red.
- Prompt embed title defaults to `Are you sure?`.
- Prompt embed color is orange.
- Cancellation responses should match existing v1 text at each call site, such as `Operation cancelled!`.

### Search And Info Action Buttons

Restore v1 `SubscribeView` surface for search and info result embeds:

- Navigation row uses the v1 paginator buttons when multiple search results are shown.
- Action buttons:
  - `Track and Subscribe` with `📚`, blurple.
  - `More Info`, blurple.
  - `Bookmark` with `🔖`, blurple.
- Navigation buttons are restricted to the command invoker when v1 restricted them.
- Action buttons remain usable by other users where v1 allowed them.
- The `More Info` button should replace the current result embed with a detailed info embed when possible.
- The `Bookmark` button should create a v1-style bookmark and respond with a green `Bookmarked!` embed.
- The `Track and Subscribe` button should track the series if the user has `Manage Roles`, then subscribe the user, and respond with a green `Subscribed to Series` embed.

Internally these buttons must call v2 stores and crawler endpoints rather than v1 scanlator classes.

### Bookmark Browser

Recreate the v1 bookmark browser user flow:

- Default mode is visual.
- Visual mode shows one bookmark using the v1-style `Bookmark: {title}` embed.
- Text mode shows grouped bookmark lists with the title `Bookmarks ({count})`.
- Controls:
  - Row 0 v1 navigation buttons.
  - `ViewTypeSelect` equivalent for visual/text switching.
  - `SortTypeSelect` equivalent in text mode.
  - `BookmarkFolderSelect` equivalent.
  - Visual-mode buttons: `Update`, `Search`, `Delete`.
  - Search opens a `Search Bookmark` modal.
  - Update exposes chapter/folder controls like v1.
  - Delete prompts with the v1 `ConfirmView`.
- The folder names and values should match v1's bookmark folder enum from a user's perspective.
- Updating the last read chapter should preserve v1 side effects where feasible:
  - If the chosen chapter is the latest chapter of an ongoing series tracked in the invoking guild, auto-subscribe the user.
  - If it is not tracked, append the v1-style hint encouraging tracking/subscribing.

### Settings

Recreate v1 settings UI shape while using v2 guild and DM settings stores:

- `/settings` sends the main settings embed and view ephemerally.
- Guild command access should remain compatible with v1: `Manage Server` or configured bot manager role.
- Main select labels and emojis should match v1:
  - `Set the updates channel`
  - `Set Default ping role`
  - `Auto create role for new tracked manhwa`
  - `Set the bot manager role`
  - `Set the system notifications channel`
  - `Show buttons for chapter updates`
  - `Custom Scanlator Channels`
  - `Notify for Paid Chapter releases`
- Dynamic controls should match v1:
  - Boolean select with `Enabled` and `Disabled`.
  - Text channel select.
  - Role select.
  - Buttons: `Save`, `Cancel`, `Delete Mode: Off`, `Delete config`.
- The custom scanlator-channel association flow should match v1 labels:
  - `New Association`
  - `Delete Association`
  - `Save changes`
  - `Discard`
  - `Delete all`
- Keep v2's more explicit warnings if they do not conflict with v1's user flow. If wording conflicts, prefer v1 wording.

## Embed And Response Style

Prefer v1 title, description, color, footer, image, and author layout when a v1 equivalent exists. Existing v2 helper functions in `formatting.py` should be extended rather than duplicating large embed-building blocks in cogs.

Important v1 response patterns to preserve:

- Standard footer: `Manhwa Updates` with bot avatar where v1 used it.
- Success embeds use green.
- Error embeds use red and title `Error` unless v1 used a more specific title.
- Search loading embed title: `Processing your request, please wait!`.
- Track success title: `Tracking Successful`.
- Subscribe success title: `Subscribed to Series`.
- Unsubscribe success title: `Unsubscribed`.
- Bookmark update title: `Bookmark Updated`.
- Stats title: `Manhwa Updates Bot Statistics`.
- Patreon title: `Patreon`.

## Data Adapters

V1 uses values such as `manga_id|scanlator`. V2 often uses `website_key:url_name` or `website_key|series_url`.

Add narrowly scoped parsing and formatting helpers so command callbacks can expose v1-like option names and user-facing text while continuing to use v2's store identifiers internally. The helpers should live close to current v2 code:

- command parsing helpers in the relevant cog when only one cog uses them;
- shared helpers only if multiple cogs need the same conversion;
- embed builders in `formatting.py`.

Do not make local files authoritative for website schema. Supported website metadata must come from the crawler-backed `supported_websites` cache.

## Testing Strategy

Use test-first implementation for each behavior change.

Focused tests should cover:

- Command metadata parity for names, descriptions, and renamed slash options where discord.py exposes this locally.
- Paginator child order, labels, styles, wraparound behavior, and stop behavior.
- Confirm view button labels and styles.
- Search/info action view button labels, emojis, styles, and invoker restriction behavior.
- Bookmark view initial mode, component set, folder switching, text/visual mode switching, and v1 embed titles.
- Settings view main select option labels, dynamic controls, and button labels.
- Embed builder output for tracking, subscription, bookmarks, chapters, supported websites, stats, Patreon, translation, help, and next update check.

Run relevant tests first:

- `python -m pytest tests/test_paginator.py`
- targeted tests for changed cogs/UI modules

Run broader tests if shared formatting, command registration, or database-store behavior changes:

- `python -m pytest`

Use v2's local virtual environment or configured Python 3.14.2 environment when the plain `python` command is not on PATH.

## Risks And Mitigations

- Exact v1 behavior sometimes depended on scanlator class methods that no longer exist in v2. Mitigate by matching the Discord-facing result while sourcing data from crawler endpoints.
- Discord slash command option values may need to stay in v2's internal format for autocomplete reliability. Mitigate by matching visible names/descriptions and response text even if hidden values differ.
- Bookmark view parity is the highest-risk area because v1 has a large interactive view with several modal/select/button flows. Mitigate by implementing it in slices: static component parity, navigation, folder/sort/mode switching, then mutating actions.
- Existing uncommitted v2 changes may already overlap with this work. Mitigate by inspecting touched files before editing and preserving user changes.

## Acceptance Criteria

- All slash commands except `/get_lost_manga` present the v1 names, descriptions, option names, and option descriptions where Discord users see them.
- Major v1 embeds and messages are restored for success, empty, and common error states.
- Shared paginated views use v1 navigation controls and behavior.
- Search/info result actions match v1 button labels, styles, and flows.
- Bookmark view matches v1 visual/text browsing and core actions.
- Settings view matches v1 component labels and flow while persisting through v2 stores.
- Tests cover the restored user-facing contract and pass locally.
