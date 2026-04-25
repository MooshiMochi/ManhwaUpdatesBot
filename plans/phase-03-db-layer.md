# Phase 3 — DB layer

> **Recommended model:** Claude **Sonnet 4.6** at **medium** reasoning effort.
> Mostly mechanical (SQL + CRUD), but the refcount logic and migrations runner
> need care. Opus is overkill; Haiku risks subtle SQL errors.

## Goal

Stand up the entire SQLite persistence layer: pool, migrations runner,
9 schema migrations, and 8 store classes that the cogs will consume. No
business logic beyond CRUD and the refcount helpers — all decisions about
*when* to insert/delete live in the cogs.

## Depends on

- Phase 2 (`src/manhwa_bot/config.py` exposes `DbConfig`).

## Files to create

```
src/manhwa_bot/db/
├── __init__.py
├── pool.py
├── migrate.py
├── migrations/
│   ├── 001_init.sql
│   ├── 002_tracked_series.sql
│   ├── 003_subscriptions.sql
│   ├── 004_bookmarks.sql
│   ├── 005_guild_settings.sql
│   ├── 006_dm_settings.sql
│   ├── 007_consumer_state.sql
│   ├── 008_premium_grants.sql
│   └── 009_patreon_links.sql
├── tracked.py
├── subscriptions.py
├── bookmarks.py
├── guild_settings.py
├── dm_settings.py
├── consumer_state.py
├── premium_grants.py
└── patreon_links.py
tests/
├── test_db_migrations.py
├── test_db_tracked_refcount.py
├── test_db_bookmarks.py
└── test_db_premium_grants.py
```

## Module specs

### `pool.py`

Wraps `aiosqlite`. Public surface:

- `class DbPool:` constructed with a path; `await DbPool.open(path)` returns
  an instance with the file opened, `PRAGMA journal_mode=WAL`, `PRAGMA
  foreign_keys=ON`, `PRAGMA synchronous=NORMAL` applied.
- `async def acquire(self) -> aiosqlite.Connection` — context manager.
- `async def execute(self, sql, params=())` and `async def fetchall(...)`,
  `fetchone(...)` convenience methods that acquire-then-release.
- `async def transaction(self) -> AsyncContextManager[Connection]` — explicit
  transaction wrapper.
- `async def close(self)` — close + final WAL checkpoint.

This is a thin wrapper, not an ORM. Stores accept a `DbPool` and call its
methods directly.

### `migrate.py`

- Reads every `*.sql` file in `migrations/`, sorted lexicographically.
- Maintains a `schema_migrations(filename TEXT PRIMARY KEY, applied_at
  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)` table (seeded by 001).
- `await apply_pending(pool: DbPool)` runs each not-yet-applied migration in
  a transaction, recording its filename. Logs each applied migration.
- Migration files contain only DDL/DML — no Python.

### Migration files

#### `001_init.sql`
```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename   TEXT PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### `002_tracked_series.sql`
```sql
CREATE TABLE tracked_series (
  website_key TEXT NOT NULL,
  url_name    TEXT NOT NULL,
  series_url  TEXT NOT NULL,
  title       TEXT NOT NULL,
  cover_url   TEXT,
  status      TEXT,
  added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (website_key, url_name)
);
CREATE TABLE tracked_in_guild (
  guild_id     INTEGER NOT NULL,
  website_key  TEXT NOT NULL,
  url_name     TEXT NOT NULL,
  ping_role_id INTEGER,
  added_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (guild_id, website_key, url_name),
  FOREIGN KEY (website_key, url_name) REFERENCES tracked_series(website_key, url_name) ON DELETE CASCADE
);
CREATE INDEX idx_tracked_in_guild_series ON tracked_in_guild(website_key, url_name);
```

#### `003_subscriptions.sql`
```sql
CREATE TABLE subscriptions (
  user_id      INTEGER NOT NULL,
  guild_id     INTEGER NOT NULL,    -- 0 for DM-only subscription
  website_key  TEXT NOT NULL,
  url_name     TEXT NOT NULL,
  subscribed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, guild_id, website_key, url_name)
);
CREATE INDEX idx_subscriptions_series ON subscriptions(website_key, url_name);
CREATE INDEX idx_subscriptions_user ON subscriptions(user_id);
```

#### `004_bookmarks.sql`
```sql
CREATE TABLE bookmarks (
  user_id            INTEGER NOT NULL,
  website_key        TEXT NOT NULL,
  url_name           TEXT NOT NULL,
  folder             TEXT NOT NULL DEFAULT 'Reading',
  last_read_chapter  TEXT,
  last_read_index    INTEGER,
  created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, website_key, url_name)
);
CREATE INDEX idx_bookmarks_user_folder ON bookmarks(user_id, folder);
```

Folder values mirror v1: `Reading`, `On Hold`, `Plan to Read`, `Re-Reading`, `Completed`, `Dropped`.

#### `005_guild_settings.sql`
```sql
CREATE TABLE guild_settings (
  guild_id                  INTEGER PRIMARY KEY,
  notifications_channel_id  INTEGER,
  system_alerts_channel_id  INTEGER,
  default_ping_role_id      INTEGER,
  paid_chapter_notifs       INTEGER NOT NULL DEFAULT 1,  -- bool 0/1
  updated_at                TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE guild_scanlator_channels (
  guild_id    INTEGER NOT NULL,
  website_key TEXT NOT NULL,
  channel_id  INTEGER NOT NULL,
  PRIMARY KEY (guild_id, website_key),
  FOREIGN KEY (guild_id) REFERENCES guild_settings(guild_id) ON DELETE CASCADE
);
```

#### `006_dm_settings.sql`
```sql
CREATE TABLE dm_settings (
  user_id              INTEGER PRIMARY KEY,
  notifications_enabled INTEGER NOT NULL DEFAULT 1,
  paid_chapter_notifs   INTEGER NOT NULL DEFAULT 1,
  updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### `007_consumer_state.sql`
```sql
CREATE TABLE consumer_state (
  consumer_key             TEXT PRIMARY KEY,
  last_acked_notification  INTEGER NOT NULL DEFAULT 0,
  updated_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

#### `008_premium_grants.sql`
```sql
CREATE TABLE premium_grants (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  scope       TEXT NOT NULL CHECK (scope IN ('user','guild')),
  target_id   INTEGER NOT NULL,
  granted_by  INTEGER NOT NULL,
  reason      TEXT,
  granted_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at  TIMESTAMP,
  revoked_at  TIMESTAMP
);
CREATE INDEX idx_premium_grants_active ON premium_grants(scope, target_id) WHERE revoked_at IS NULL;
```

#### `009_patreon_links.sql`
```sql
CREATE TABLE patreon_links (
  discord_user_id INTEGER PRIMARY KEY,
  patreon_user_id TEXT NOT NULL,
  tier_ids        TEXT NOT NULL,    -- JSON array
  cents           INTEGER NOT NULL,
  refreshed_at    TIMESTAMP NOT NULL,
  expires_at      TIMESTAMP NOT NULL
);
```

### Store classes

Each store class:
- Takes a `DbPool` in `__init__`.
- Exposes async methods that mirror SQL semantics 1:1.
- Returns frozen dataclasses (not raw rows) for callers.
- Uses parameterized queries; never string-formats user data into SQL.

#### `tracked.py`
- `TrackedSeries` dataclass: `(website_key, url_name, series_url, title, cover_url, status, added_at)`
- `GuildTrackedSeries` dataclass: above + `(guild_id, ping_role_id)`
- `TrackedStore`:
  - `upsert_series(...)` — insert/update master row
  - `add_to_guild(guild_id, website_key, url_name, ping_role_id)`
  - `update_ping_role(guild_id, website_key, url_name, ping_role_id)`
  - `remove_from_guild(guild_id, website_key, url_name) -> tuple[bool, int]` returns `(was_last_guild, remaining_guild_count)` — first bool tells the cog whether to call crawler `untrack_series`.
  - `delete_series(website_key, url_name)` — only call when last guild dropped
  - `list_for_guild(guild_id, *, limit, offset)` — paginated
  - `find(website_key, url_name)` — one-row lookup
  - `list_guilds_tracking(website_key, url_name)` — for the updates cog dispatch
  - `count_for_guild(guild_id) -> int`

#### `subscriptions.py`
- `SubscriptionStore`:
  - `subscribe(user_id, guild_id, website_key, url_name)` — INSERT OR IGNORE
  - `unsubscribe(user_id, guild_id, website_key, url_name)`
  - `unsubscribe_all_for_user(user_id, *, guild_id=None)`
  - `list_for_user(user_id, *, guild_id=None, limit, offset)`
  - `list_subscribers_for_series(website_key, url_name, *, guild_id=None) -> list[int]` (user IDs)
  - `is_subscribed(user_id, guild_id, website_key, url_name) -> bool`

#### `bookmarks.py`
- `Bookmark` dataclass with all columns.
- `BookmarkStore`:
  - `upsert_bookmark(...)` — UPSERT including folder + last_read_*
  - `get_bookmark(user_id, website_key, url_name) -> Bookmark | None`
  - `list_user_bookmarks(user_id, *, folder=None, limit, offset)`
  - `delete_bookmark(user_id, website_key, url_name)`
  - `update_last_read(user_id, website_key, url_name, *, chapter_text, chapter_index)`
  - `update_folder(user_id, website_key, url_name, folder)`
  - `count_for_user(user_id) -> int`

Folder validation lives in the cog, not here.

#### `guild_settings.py`
- `GuildSettings` dataclass.
- `GuildSettingsStore`:
  - `get(guild_id) -> GuildSettings | None`
  - `upsert(GuildSettings)` — single SQL, all fields
  - `set_notifications_channel`, `set_system_alerts_channel`,
    `set_default_ping_role`, `set_paid_chapter_notifs` — narrow setters
  - `set_scanlator_channel(guild_id, website_key, channel_id)` /
    `clear_scanlator_channel(...)` / `list_scanlator_channels(guild_id)`

#### `dm_settings.py`
- `DmSettings` dataclass.
- `DmSettingsStore`:
  - `get(user_id) -> DmSettings | None`
  - `upsert(DmSettings)`
  - `set_notifications_enabled(user_id, enabled)`
  - `set_paid_chapter_notifs(user_id, enabled)`

#### `consumer_state.py`
- `ConsumerStateStore`:
  - `get_last_acked(consumer_key) -> int` (0 if absent)
  - `set_last_acked(consumer_key, notification_id)` — UPSERT

#### `premium_grants.py`
- `PremiumGrant` dataclass.
- `PremiumGrantStore`:
  - `grant(scope, target_id, granted_by, reason, expires_at) -> int`
  - `revoke(grant_id)` / `revoke_for_target(scope, target_id)`
  - `list(scope=None, active_only=True, limit, offset)`
  - `find_active(scope, target_id) -> PremiumGrant | None`
  - `sweep_expired() -> int` (returns row count auto-revoked)

Active grant: `revoked_at IS NULL AND (expires_at IS NULL OR expires_at > strftime('%s','now')*1000)` — store timestamps as ISO strings or epoch ms; pick one and stay consistent (recommend ISO via `datetime.utcnow().isoformat()`).

#### `patreon_links.py`
- `PatreonLink` dataclass.
- `PatreonLinkStore`:
  - `upsert(discord_user_id, patreon_user_id, tier_ids, cents, refreshed_at, expires_at)`
  - `get(discord_user_id) -> PatreonLink | None`
  - `is_active(discord_user_id) -> bool` — fresh + not expired
  - `delete(discord_user_id)`
  - `list_active() -> list[PatreonLink]`

## Tests

All tests follow the `asyncio.run()`-with-inner-`async def _run()` pattern (no pytest-asyncio).

- `test_db_migrations.py` — empty file → all 9 migrations apply → schema_migrations has 9 rows. Re-running is a no-op.
- `test_db_tracked_refcount.py` — two guilds add same series; first `remove_from_guild` returns `was_last_guild=False`; second returns `True`. Confirm `delete_series` cascades `tracked_in_guild`.
- `test_db_bookmarks.py` — upsert, list by folder, update_last_read, delete; folder index is used (assert via `EXPLAIN QUERY PLAN`).
- `test_db_premium_grants.py` — grant + find_active; expiry past now → not active; revoke → not active; sweep_expired auto-revokes.

Use a `tmp_path / "test.db"` fixture per test.

## Verification

```bash
python -m ruff check src/manhwa_bot/db tests/test_db_*.py
python -m ruff format --check src/manhwa_bot/db tests/test_db_*.py
python -m pytest tests/test_db_*.py -v
```

All tests must pass before committing.

## Commit message

```
Add SQLite persistence layer: pool, migrations, store classes

- src/manhwa_bot/db/pool.py: aiosqlite wrapper with WAL, FK, transactions
- src/manhwa_bot/db/migrate.py: file-based migrations with schema_migrations table
- 9 SQL migrations covering tracked series, subscriptions, bookmarks,
  guild/DM settings, consumer state, premium grants, Patreon links
- 8 store classes with frozen dataclass returns and parameterized queries
- Tests for migrations idempotency, refcount semantics, bookmark folder
  index, and premium-grant lifecycle
```
