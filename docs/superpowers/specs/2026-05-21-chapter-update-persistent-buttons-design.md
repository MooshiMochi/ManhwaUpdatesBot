# Chapter Update View: Persistent Buttons & Multi-Select Settings

## Context

Three intertwined changes to the new-chapter notification flow:

1. **Bug fix.** `/settings` raises `discord.errors.NotFound (10062)` when picking the updates channel. Root cause: `SettingsLayoutView._refresh()` runs two DB queries before calling `interaction.response.edit_message`. If the queries exceed Discord's 3-second interaction window, the token expires.
2. **Update view.** Add four optional buttons (Mark Read, Bookmark, Subscribe, Open Chapter) to the chapter update LayoutView. Buttons must survive bot restart.
3. **Settings.** Convert `guild_settings.show_update_buttons` / `dm_settings.show_update_buttons` from a boolean toggle into a multi-select of which buttons to show. Empty selection means no buttons.

## Goals / Non-goals

**Goals**

- Eliminate the 404 in `/settings` when changing the updates channel (and related DB-write callbacks).
- Replace the boolean show/hide setting with a four-key multi-select, persisted in `update_buttons TEXT` columns.
- Render the chapter update view as Components V2 with no container accent colour and an optional ActionRow of buttons driven by the per-guild / per-DM setting.
- Make the interactive buttons persistent across bot restarts via `discord.ui.DynamicItem`.

**Non-goals**

- No changes to the notification fan-out / consumer ack pipeline.
- No changes to the v1 legacy embed code (it is already removed; the existing `build_chapter_update_view` is the source of truth).
- No new buttons beyond the four listed.
- No fix for unrelated `except discord.HTTPException, AttributeError:` parsing-quirk in `base.py:256` — flagged as a separate task.

## Design

### A. `/settings` 404 fix

`SettingsLayoutView._refresh` defers the interaction up-front so the token survives the DB queries, then uses `edit_original_response` to push the updated view:

```python
async def _refresh(self, interaction: discord.Interaction) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer()
    self._settings = await self._store.get(self._guild_id)
    self._scanlator_overrides = await self._store.list_scanlator_channels(self._guild_id)
    guild = interaction.guild
    me = guild.me if guild else None
    self._warnings = collect_warnings(self._settings, guild, me) if guild and me else []
    self._rebuild()
    await interaction.edit_original_response(view=self)
```

All callbacks that flow through `_refresh` (`_on_channel_picked`, `_on_role_picked`, `_on_bool_picked`, the new `_on_buttons_picked`, `_on_delete_mode`) inherit the fix. Callbacks that call `interaction.response.edit_message` directly without DB writes (`_on_main_select`) stay unchanged.

### B. Chapter update view + persistent buttons

#### View factory

`src/manhwa_bot/ui/components/notifications.py` exposes:

```python
UPDATE_BUTTON_KEYS = ("mark_read", "bookmark", "subscribe", "open_chapter")
ALL_UPDATE_BUTTONS = frozenset(UPDATE_BUTTON_KEYS)

def build_chapter_update_view(
    payload: dict,
    *,
    bot: discord.Client | None,
    allowed_buttons: frozenset[str] = ALL_UPDATE_BUTTONS,
) -> discord.ui.LayoutView
```

- The container is built plain (`discord.ui.Container()` — no `accent_colour`).
- Cover gallery, header, body, footer match the current factory.
- If `allowed_buttons` is non-empty an `ActionRow` is appended to the container with one item per selected key, **in the canonical `UPDATE_BUTTON_KEYS` order**.
- The returned `BaseLayoutView` is constructed with `timeout=None` so the buttons remain active indefinitely.

#### Persistent buttons via `DynamicItem`

`src/manhwa_bot/ui/components/notification_buttons.py` defines four `discord.ui.DynamicItem[discord.ui.Button]` subclasses. Each parses its own `custom_id` and runs the action on click.

`custom_id` scheme (all `:`-separated, ≤100 chars):

| Button     | Pattern                                                      |
|------------|--------------------------------------------------------------|
| Mark Read  | `mu:upd:mr:<website_key>:<url_name>:<chapter_index>`         |
| Bookmark   | `mu:upd:bm:<website_key>:<url_name>`                         |
| Subscribe  | `mu:upd:sub:<website_key>:<url_name>`                        |
| Open       | (no custom_id — `discord.ButtonStyle.link` with `url=`)      |

`website_key` and `url_name` are server-supplied slugs that never contain `:`. The view factory asserts this and raises early if violated. The encoded `chapter_index` is the chapter's position in the latest series listing at notification time — treated as a hint at click time, with the actual index resolved from `series_data` so retroactive insertions don't desync.

```python
class MarkReadButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"mu:upd:mr:(?P<wk>[^:]+):(?P<un>[^:]+):(?P<idx>-?\d+)",
):
    def __init__(self, website_key: str, url_name: str, chapter_index: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Mark Read",
                style=discord.ButtonStyle.secondary,
                emoji="✅",
                custom_id=f"mu:upd:mr:{website_key}:{url_name}:{chapter_index}",
            )
        )
        self.website_key = website_key
        self.url_name = url_name
        self.chapter_index = chapter_index

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["wk"], match["un"], int(match["idx"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        # Resolve current chapter via series_data, upsert bookmark in "Reading",
        # set last_read_index / last_read_chapter. Send ephemeral confirm.
```

Bookmark and Subscribe follow the same shape — defer ephemerally, do the DB write, send a short confirmation.

Subscribe-specific check: it needs a mutual guild that tracks this series. If the clicker isn't a member of any guild tracking `(website_key, url_name)`, send an ephemeral "You're not in a server that tracks this series — bookmark it from your DMs instead" message. In DM context, the same fallback applies.

#### Registration

`ManhwaBot.setup_hook` calls `self.add_dynamic_items(MarkReadButton, BookmarkButton, SubscribeToggleButton)` once. This makes the bot's view registry route any matching `custom_id` (from messages posted before the restart) into the dynamic item callback.

The link `Open Chapter` button is built from `chapter.url` at notification time and stored in the message body — link buttons need no registration.

### C. Settings: multi-select for update buttons

#### Schema migration

New migration `004_update_buttons_multiselect.sql` (number adapted to next free index):

```sql
ALTER TABLE guild_settings ADD COLUMN update_buttons TEXT NOT NULL DEFAULT 'mark_read,bookmark,subscribe,open_chapter';
UPDATE guild_settings SET update_buttons = '' WHERE show_update_buttons = 0;
ALTER TABLE guild_settings DROP COLUMN show_update_buttons;

ALTER TABLE dm_settings ADD COLUMN update_buttons TEXT NOT NULL DEFAULT 'mark_read,bookmark,subscribe,open_chapter';
UPDATE dm_settings SET update_buttons = '' WHERE show_update_buttons = 0;
ALTER TABLE dm_settings DROP COLUMN show_update_buttons;
```

Stored as a comma-separated list of keys from `UPDATE_BUTTON_KEYS`. Empty string = no buttons.

#### Dataclass / store changes

`GuildSettings` and `DmSettings` replace `show_update_buttons: bool` with `update_buttons: frozenset[str]`. Row parsers split on `,` and filter to valid keys (silently dropping unknowns).

`GuildSettingsStore` / `DmSettingsStore` gain `set_update_buttons(scope_id, keys: Iterable[str])` which `,`-joins after sorting by `UPDATE_BUTTON_KEYS` order (stable storage).

#### Settings view

In `settings.py`:

- Constant rename: `_SETTING_SHOW_UPDATE_BUTTONS` → `_SETTING_UPDATE_BUTTONS`. `_BOOL_SETTINGS` no longer includes it.
- `_MAIN_OPTIONS` entry label: "Buttons shown on chapter updates". Description: "Pick which buttons appear on chapter update messages."
- New branch in `_on_main_select` builds a multi-select:

  ```python
  current = self._settings.update_buttons if self._settings else ALL_UPDATE_BUTTONS
  select = discord.ui.Select(
      placeholder="Pick buttons to show (or none)…",
      min_values=0,
      max_values=len(UPDATE_BUTTON_KEYS),
      options=[
          discord.SelectOption(
              label=UPDATE_BUTTON_LABELS[k][0],
              value=k,
              emoji=UPDATE_BUTTON_LABELS[k][1],
              description=UPDATE_BUTTON_LABELS[k][2],
              default=(k in current),
          )
          for k in UPDATE_BUTTON_KEYS
      ],
  )
  ```

- New callback `_on_buttons_picked` reads `item.values` (possibly empty), calls `set_update_buttons`, then `_refresh`.
- The summary container line changes from `_bool_emoji` to: comma-joined labels of selected buttons, or `Disabled` when empty.

DM settings (`DmSettingsLayoutView`) mirrors this: the existing "🔘 Update Buttons" toggle button row is replaced with a multi-select row. The other two DM toggles (DM notifications, Paid chapter notifs) stay as buttons.

#### Notification dispatch

In `UpdatesCog`:

- `_dispatch_to_guild`: `allowed_buttons = settings.update_buttons if settings else ALL_UPDATE_BUTTONS`.
- `_dispatch_to_user`: `allowed_buttons = dm_settings.update_buttons if dm_settings else ALL_UPDATE_BUTTONS`.

Default-when-no-row mirrors current behavior (show all buttons when the user/guild has never customised).

## Data flow

```
crawler push -> UpdatesCog.dispatch
  -> fetch GuildSettings.update_buttons (or DmSettings)
  -> build_chapter_update_view(payload, allowed_buttons=...)
  -> channel.send(view=...)         # buttons embedded with persistent custom_ids

user click (any time, even post-restart)
  -> discord.py finds matching DynamicItem template
  -> DynamicItem.from_custom_id rebuilds the item with parsed (wk, un, idx)
  -> callback defers ephemerally, performs DB write, replies ephemerally
```

## Edge cases

- **`url_name` with `:`.** Asserted out at view build time. Slugs in the schema have never contained `:`; we fail loudly if a new schema breaks the assumption.
- **`chapter_index` shifted by retroactive inserts.** Mark Read resolves the chapter by index against the current series listing; if the chapter at that index doesn't match the URL recorded in the message, it falls back to a URL lookup and updates `last_read_index` to the resolved position.
- **Mark Read with no existing bookmark.** Auto-creates a bookmark in the "Reading" folder, then sets `last_read_*`. Ephemeral confirm mentions the folder.
- **Subscribe in DM context.** No mutual guild — reply ephemerally explaining tracking is per-guild.
- **Empty `update_buttons` set.** View factory returns the container without any ActionRow. Link button is also omitted (it's part of the same conditional list).
- **Settings row absent.** Default is the full set (current behavior parity).
- **Restart after old messages.** Old messages still in channels carry the new custom_id scheme because we cut over once; we don't promise to support clicks on pre-rollout notifications.

## Test plan

Update / new tests:

- `tests/test_notification_dispatch.py`: assertions tied to `show_update_buttons` swap to `update_buttons`; new test for default-all when row absent.
- `tests/test_component_button_layout.py`: assert button presence by `allowed_buttons` permutations (none, all, subset).
- New `tests/test_chapter_update_buttons_dynamic.py`: confirm each DynamicItem's `template` round-trips for representative `(website_key, url_name, chapter_index)` triples.
- New `tests/test_settings_update_buttons_multiselect.py`: settings view renders multi-select with current defaults; saving empty / partial / full updates the store.
- Existing `tests/test_scraping_service_progress.py` (crawler) — unaffected.

Manual smoke test (live):

1. `/settings` → pick "Set the updates channel" → choose channel. No 404; settings re-render. (Section A.)
2. `/settings` → pick the new multi-select; toggle off all four buttons; save. New chapter update arrives → no buttons row. Re-enable just Mark Read → next update has only that button. (Section C.)
3. Restart the bot; click Mark Read on a pre-restart message — the callback fires and the bookmark is updated. (Section B / DynamicItem registration.)

## Risks & mitigations

- **Migration runs on production data** — schema changes ADD then DROP, with `WHERE show_update_buttons = 0` first. Reviewed for SQLite 3.35+ compatibility (drop column supported). If we discover an older SQLite, fall back to `CREATE TABLE … AS SELECT` rebuild within the same migration.
- **Long `url_name`** — pre-check that the constructed `custom_id` is ≤100 chars; truncate the encoded index portion to error fast in a unit test.
- **DynamicItem inside LayoutView** — confirmed supported by discord.py 2.7.x. Tests cover this via construction.
