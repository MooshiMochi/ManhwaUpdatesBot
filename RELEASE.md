# ManhwaUpdatesBot v2.0 Release Notes

## Summary

ManhwaUpdatesBot v2.0 is a clean-slate Discord bot that keeps the v1 command
surface while delegating manga scraping, search, info lookup, chapter lists, and
update detection to the crawler service.

The v1 implementation is preserved on the `v1` branch. The v2 codebase is on
`main`.

## Verification

Automated verification on 2026-04-26:

- `python -m ruff check .` passed.
- `python -m ruff format --check .` passed.
- `python -m pytest -v` passed with 106 tests.

Manual live verification still requires local deployment credentials:

- `DISCORD_BOT_TOKEN`
- `CRAWLER_API_KEY`
- Optional `PATREON_ACCESS_TOKEN`
- Test Discord guild access

Run the smoke checklist in `plans/phase-15-verification.md` against a local
crawler and Discord test guild before production rollout.

## Scope

All 15 planned phases have landed:

- Clean v2 repository structure
- Config loader and crawler WebSocket client
- SQLite migrations and stores
- Bot skeleton and cog loading
- Three-source premium checks
- Catalog, tracking, subscription, bookmark, settings, updates, general, and dev
  cogs
- Docs, Dockerfile, CI, and final automated verification
