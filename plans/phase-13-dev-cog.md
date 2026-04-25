# Phase 13 — Dev cog (prefix-mention commands + crawler health + premium management)

> **Recommended model:** Claude **Opus 4.7** at **medium** reasoning effort.
> Eval, sql, and import_db handlers have a wide blast radius if mishandled.
> Many small commands but each touches sensitive paths. Drop to Sonnet
> for follow-up edits.

## Goal

Owner-only operations cog. v1's `developer` group (aliases `d`, `dev`)
preserved verbatim, invoked via `@ManhwaUpdatesBot d <subcommand>` (works
without `message_content` intent because mentions deliver content). Adds
crawler health probes and premium-grant management.

## Depends on

- Phase 4 (bot skeleton with `commands.when_mentioned` prefix)
- Phase 5 (premium services for grant/revoke/check)
- Phase 6 (`bot.websites_cache.invalidate()` for crawler websites refresh)
- Crawler ops: `schema_health_list`, `schema_health_test`,
  `schema_healing_run`, `supported_websites`.

## Reference v1

```bash
git show v1:src/ext/dev.py | less
```

Mirror function names and behavior 1:1 except for `toggle_scanlator`
(removed) and the new crawler/premium subgroups.

## Files

```
src/manhwa_bot/cogs/dev.py
src/manhwa_bot/dev_helpers/
├── __init__.py
├── eval_runner.py            # async exec sandbox helper
├── sql_runner.py             # parameterized query helper
├── duration_parser.py        # "7d", "48h", "1mo", "permanent", ISO
└── shell_runner.py           # asyncio.create_subprocess_exec wrapper
```

Append `"manhwa_bot.cogs.dev"` to `COGS`.

## Module spec — `cogs/dev.py`

All commands `@commands.is_owner()`. The parent group:

```python
@commands.group(name="developer", aliases=["d", "dev"], invoke_without_command=True)
async def developer(self, ctx):
    await ctx.send("Use `@bot d <subcommand>`. See `@bot d loaded_cogs`.")
```

### Verbatim from v1

- `restart` — write a recovery file, then `os.execv` (or `sys.exit(0)` if
  using a process manager).
- `sync [guilds...] [spec]` — `~` syncs to current guild, `*` copies
  global to current, `^` clears guild, `^^` clears global. Else syncs
  globally.
- `pull` — `git pull --ff-only`; if changes, reload all extensions.
- `loaded_cogs` — list `bot.extensions.keys()`.
- `shell <cmd>` / `sh` — runs the command, paginates output via
  `Paginator` (Phase 6).
- `get_emoji <emojis...>` / `gib` / `get` — downloads attached PartialEmoji
  bytes and uploads as a guild emoji.
- `source <command>` — `inspect.getsource(...)`. Wrap in code block.
- `load <name>` / `unload <name>` / `reload <name>`.
- `eval <code>` — uses `dev_helpers/eval_runner.py` to async-exec; injects
  `bot`, `ctx`, `db`, `crawler`, `premium`. Captures stdout. Pretty-prints
  the result. **Do not** add user-friendly error wrapping — owners want
  the raw traceback.
- `logs [view|clear]` — read/truncate `manhwa_bot.log` if log file is
  configured (optional; if logs go to stdout only, this command warns).
- `export_db [raw=false]` — if `raw`, attach the SQLite file directly
  (zip if too large). Else dump to JSON via store classes.
- `import_db` — reads `ctx.message.attachments[0]`. If `.sqlite`/`.db`,
  swap (with backup of current). If `.json`, validate-then-replay.
- `sql <query>` — runs against the bot's SQLite. Args passed via
  `--args=value1,value2,...` flag parsed in-cog. Print rows as a markdown
  table.
- `disabled_scanlators` / `dscan` — calls
  `crawler.request("schema_health_list")` and shows `works=False` rows.
  (v1 stored the list locally; in v2 the crawler owns it.)
- `g_update <message>` — broadcasts an embed to every guild's
  `system_alerts_channel_id`. Confirmation prompt before fan-out.
- `test_update` — synthesizes a fake `notification_event` and calls
  `bot.cogs["UpdatesCog"].dispatch(...)` with it; routed to the invoking
  guild's notif channel.
- **`toggle_scanlator` REMOVED** (crawler owns it).

### New subgroups

#### `crawler` — health probes

```
@bot d crawler health [website_key]
@bot d crawler heal <website_key> <series_url> [--dry-run]
@bot d crawler test <website_key> [--series=<url>] [--query=<text>]
@bot d crawler websites
```

- `crawler health` calls `schema_health_list`. Shows table.
- `crawler heal` calls `schema_healing_run` with `dry_run`.
- `crawler test` calls `schema_health_test` with optional series_url
  and/or search_query.
- `crawler websites` calls `supported_websites` bypassing
  `bot.websites_cache` and prints. Also invalidates the cache so the next
  user-facing autocomplete sees fresh data.

#### `premium` — grant management

```
@bot d premium grant <user|guild> <id> <duration> [reason...]
@bot d premium revoke <grant_id>
@bot d premium revoke <user|guild> <id>          # revoke all active for target
@bot d premium list [user|guild|all] [active=true]
@bot d premium check <@user>
@bot d premium patreon refresh
@bot d premium patreon link <@user> <patreon_user_id>
```

- `grant` parses `duration` via `duration_parser.parse(...)` →
  `datetime | None`. Inserts via `bot.premium.grants.grant(...)`.
- `revoke` either by id or by scope+target. Confirm before bulk revokes.
- `list` paginates via the Paginator from Phase 6.
- `check` calls `bot.premium.is_premium(...)` for the target and shows
  `(ok, reason)` + which sources qualified (separately call each source
  for the breakdown).
- `patreon refresh` triggers `await bot.patreon.refresh()` ad-hoc.
- `patreon link` upserts `patreon_links` directly (bypasses the API
  poll — for users whose social-connection flow is broken).

## Tests

- `test_duration_parser.py` — `"7d"` → 7 days; `"48h"` → 2 days; `"1mo"` →
  ~30 days; `"permanent"` → None; ISO strings parse; bad strings raise.
- The rest is integration-tested manually.

## Verification

```bash
python -m ruff check src/manhwa_bot/cogs/dev.py src/manhwa_bot/dev_helpers
python -m pytest tests/test_duration_parser.py -v
```

Manual (in owner home guild):
- `@bot d sync ~` — registers slash commands in this guild.
- `@bot d loaded_cogs`.
- `@bot d eval print(bot.user)` — outputs the bot user.
- `@bot d crawler health` — table.
- `@bot d premium grant user 123456789 7d testing` → row inserted; verify
  with `@bot d premium check <@user>` showing `source=grant_user`.
- `@bot d premium revoke <id>` → check returns no source.
- `@bot d test_update` posts a fake new-chapter embed.

## Commit message

```
Add dev cog: prefix-mention owner ops + crawler health + premium mgmt

Mirror of v1's developer group invoked as `@bot d <cmd>` (works without
message_content intent thanks to mention-based content delivery). Adds
crawler health/test/heal probes and full premium-grant management
(grant/revoke/list/check + Patreon refresh and manual link). Removes
toggle_scanlator (crawler-owned in v2).
```
