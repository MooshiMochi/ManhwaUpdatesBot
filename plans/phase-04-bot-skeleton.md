# Phase 4 — Bot skeleton

> **Recommended model:** Claude **Sonnet 4.6** at **medium** reasoning effort.
> The intents wiring and lifecycle are subtle (especially the
> `commands.when_mentioned` prefix and the cog-loading order), but no
> deep reasoning required.

## Goal

Stand up the `commands.Bot` subclass, the application entry point, and the
service container that holds the DB pool, crawler client, and (in later
phases) premium service. After this phase the bot connects to Discord and
the crawler, applies migrations on startup, and shuts down cleanly — but
no cogs are loaded yet, so it's a silent member.

## Depends on

- Phase 2 (`config.py`, `crawler/client.py`, `log.py`)
- Phase 3 (`db/pool.py`, `db/migrate.py`)

## Files to create

```
src/manhwa_bot/
├── app.py
├── bot.py
├── __main__.py
main.py                      # at repo root
```

## Module specs

### `bot.py` — `ManhwaBot(commands.Bot)`

```python
class ManhwaBot(commands.Bot):
    config: AppConfig
    db: DbPool
    crawler: CrawlerClient
    # premium: PremiumService    # added in Phase 5
    # patreon: PatreonClient     # added in Phase 5
    started_at: datetime
```

Construction:

- `command_prefix=commands.when_mentioned` (so prefix commands work without `message_content` intent).
- `intents = discord.Intents.default()`; explicitly set `members=True`, `message_content=False`, `presences=False`.
- `help_command=None` (the general cog provides `/help`).
- `case_insensitive=True` for prefix commands.
- `owner_ids=set(config.bot.owner_ids)`.
- Allowed mentions: deny `@everyone`/`@here`, allow roles (we explicitly
  ping `tracked_in_guild.ping_role_id`), allow user mentions.

`async def setup_hook(self)` runs before login and:
1. Logs the resolved intents and warns loudly if `members` is missing.
2. Applies DB migrations via `migrate.apply_pending(self.db)`.
3. Starts the crawler client (`await self.crawler.start()`).
4. Loads cogs from `manhwa_bot.cogs.COGS` (a list defined in
   `cogs/__init__.py`; in Phase 4 it's an empty list — later phases append
   to it).
5. Syncs the global app-command tree if a flag is set (do NOT auto-sync on
   every boot — slow; instead expose `dev sync` for owners).

`async def close(self)` performs orderly shutdown:
1. Stop the crawler client (`await self.crawler.stop()`).
2. Close the DB pool.
3. Call `super().close()`.

Override `process_commands` to be a guard: only process if the message
mentions the bot or is in a DM. discord.py's behavior covers this already,
but adding a defensive check costs nothing.

### `app.py` — `async def run() -> None`

1. `load_config()` — fail fast if secrets are missing.
2. `log.configure(config.bot.log_level)`.
3. Build `DbPool`, `CrawlerClient`, `ManhwaBot`.
4. Wire them onto the bot instance.
5. `await bot.start(config.discord_bot_token)` inside a `try`/`finally`
   that calls `bot.close()`.

Handle `KeyboardInterrupt` gracefully (log and exit 0).

### `__main__.py`

```python
import asyncio
from .app import run

if __name__ == "__main__":
    asyncio.run(run())
```

### `main.py` (repo root)

```python
"""Bot entry point. The only Python file allowed at the repository root."""
from __future__ import annotations
import asyncio
from src.manhwa_bot.app import run

if __name__ == "__main__":
    asyncio.run(run())
```

This duplicates `__main__.py` so `python main.py` works from the repo root
(matches crawler convention).

## Cogs scaffold

Create `src/manhwa_bot/cogs/__init__.py`:

```python
"""Cog registry — appended to as phases land."""
COGS: list[str] = []
```

Each later phase will add its module path to `COGS`.

## Tests

- `tests/test_bot_skeleton.py`:
  - Import `ManhwaBot`, instantiate without connecting (pass a fake config).
  - Assert intents are exactly `members=True, message_content=False, presences=False`.
  - Assert `command_prefix is commands.when_mentioned`.
  - Assert `help_command is None`.
- `tests/test_app_smoke.py`:
  - `await app.run()` with a config pointing at an unreachable Discord
    endpoint times out cleanly when given a fake token + cancelled task —
    proves shutdown sequence runs without exceptions. (Optional; mostly
    covered by manual runs.)

## Verification

```bash
python -m ruff check . tests/
python -m ruff format --check .
python -m pytest tests/test_bot_skeleton.py -v
# Manual: with .env + config.toml filled, `python main.py` should
# log "logged in as <bot>", connect to crawler, then idle. Ctrl+C
# should exit cleanly with no traceback.
```

## Commit message

```
Add bot skeleton: ManhwaBot, app entrypoint, intents wiring

- src/manhwa_bot/bot.py: commands.Bot subclass with mention-only prefix,
  members intent on, message_content/presences off, ordered setup_hook
  (migrations → crawler → cog load) and clean close
- src/manhwa_bot/app.py: load config, configure logging, build services,
  start the bot
- src/manhwa_bot/__main__.py + main.py: entry points
- src/manhwa_bot/cogs/__init__.py: empty COGS registry, populated by
  later phases
- Tests: intent assertions, prefix check
```
