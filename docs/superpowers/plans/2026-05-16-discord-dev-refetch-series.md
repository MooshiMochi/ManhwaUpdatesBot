# Discord Dev Refetch Series Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `?d refetch` to ManhwaUpdatesBot so owners can force crawler_backend to refresh and persist a series snapshot.

**Architecture:** Extend the existing owner-only `DevCog` command group. The command detects `website_key` for URL input through existing supported-website helpers, then sends the existing crawler `series_data` request with `refresh=True` and `allow_live=True`.

**Tech Stack:** Python 3.14, discord.py prefix commands, pytest, existing `CrawlerClient` request API.

---

### Task 1: Add Refetch Tests

**Files:**
- Create: `tests/test_dev_refetch.py`
- Modify: none

- [ ] **Step 1: Write failing tests**

Add tests that call `DevCog.refetch.callback(...)` with URL input and with `website_key + url_name`, then assert the crawler request payload includes `series_data`, `refresh=True`, and `allow_live=True`.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/test_dev_refetch.py -q`
Expected: FAIL because `DevCog` has no `refetch` command.

### Task 2: Implement Dev Command

**Files:**
- Modify: `src/manhwa_bot/cogs/dev.py`
- Test: `tests/test_dev_refetch.py`

- [ ] **Step 1: Add help text and imports**

Add `detect_website_key`, `series_url_from_maybe_chapter_url`, `Disconnected`, and `RequestTimeout` imports. Add `"refetch": "Fetch fresh series data and overwrite the crawler DB snapshot."` to `_DEV_COMMAND_DESCRIPTIONS`.

- [ ] **Step 2: Add command implementation**

Add `@developer.command(name="refetch")` in `DevCog`. It accepts `first: str` and `second: str | None = None`, chooses URL mode when `first` starts with `http://` or `https://`, otherwise requires `second`, then calls `self.bot.crawler.request("series_data", ..., refresh=True, allow_live=True)`. It sends a diagnostic view containing the returned fields.

- [ ] **Step 3: Run tests to verify pass**

Run: `python -m pytest tests/test_dev_refetch.py -q`
Expected: PASS.

### Task 3: Verification

**Files:**
- Modify: none
- Test: `tests/test_dev_refetch.py`, `tests/test_crawler_client.py`

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_dev_refetch.py tests/test_crawler_client.py -q`
Expected: PASS.

- [ ] **Step 2: Run lint on touched files**

Run: `python -m ruff check src/manhwa_bot/cogs/dev.py tests/test_dev_refetch.py`
Expected: PASS.
