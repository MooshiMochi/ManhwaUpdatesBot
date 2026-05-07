# V1 Command Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore v1 Discord-facing command metadata, embeds, views, and interaction flows in v2 while preserving crawler-backed internals.

**Architecture:** Implement a v1 UX compatibility layer in existing v2 cogs and UI modules. Shared UI primitives are restored first, then command metadata, then search/info, bookmarks, and settings flows.

**Tech Stack:** Python 3.14, discord.py 2.x, pytest, aiosqlite-backed stores, crawler client abstractions.

---

## File Structure

- Modify: `src/manhwa_bot/ui/paginator.py` - v1 navigation labels, styles, wraparound, stop, and unauthorized-user response.
- Modify: `src/manhwa_bot/ui/confirm_view.py` - v1 `Confirm` / `Cancel` labels and prompt helper.
- Modify: `src/manhwa_bot/ui/subscribe_view.py` - v1 search/info action buttons and crawler-backed button callbacks.
- Modify: `src/manhwa_bot/ui/bookmark_view.py` - v1 visual/text bookmark browser components and modal/select actions.
- Modify: `src/manhwa_bot/ui/settings_view.py` - v1 settings component labels and association flow labels.
- Modify: `src/manhwa_bot/cogs/tracking.py` - v1 command metadata and option renames.
- Modify: `src/manhwa_bot/cogs/subscriptions.py` - v1 command metadata and option renames.
- Modify: `src/manhwa_bot/cogs/bookmarks.py` - v1 command metadata and option renames.
- Modify: `src/manhwa_bot/cogs/catalog.py` - v1 command metadata, option renames, and v1 action views.
- Modify: `src/manhwa_bot/cogs/general.py` - v1 command metadata, excluding `/get_lost_manga`.
- Modify: `src/manhwa_bot/cogs/settings.py` - v1 settings command description.
- Modify: `src/manhwa_bot/formatting.py` - add or adjust v1 embed builders used by UI/cogs.
- Create/modify tests:
  - `tests/test_paginator.py`
  - `tests/test_confirm_view.py`
  - `tests/test_command_metadata_parity.py`
  - `tests/test_subscribe_view.py`
  - `tests/test_bookmark_view_parity.py`
  - `tests/test_settings_view_parity.py`

---

### Task 1: Shared Paginator And Confirm View Parity

**Files:**
- Modify: `src/manhwa_bot/ui/paginator.py`
- Modify: `src/manhwa_bot/ui/confirm_view.py`
- Modify: `tests/test_paginator.py`
- Create: `tests/test_confirm_view.py`

- [ ] **Step 1: Write failing paginator tests**

Replace the current expectations in `tests/test_paginator.py` so the first five children are v1 labels and styles:

```python
def test_multi_page_first_page_state() -> None:
    p = Paginator(_embeds(3))
    first, prev, stop, nxt, last = _nav_buttons(p)

    assert [b.label for b in (first, prev, stop, nxt, last)] == ["⏮️", "⬅️", "⏹️", "➡️", "⏭️"]
    assert first.style is discord.ButtonStyle.blurple
    assert prev.style is discord.ButtonStyle.blurple
    assert stop.style is discord.ButtonStyle.red
    assert nxt.style is discord.ButtonStyle.blurple
    assert last.style is discord.ButtonStyle.blurple
    assert not first.disabled
    assert not prev.disabled
    assert not stop.disabled
    assert not nxt.disabled
    assert not last.disabled
```

Add wraparound unit coverage by setting `p._page` and calling the page mutation helper directly:

```python
def test_prev_wraps_from_first_to_last() -> None:
    p = Paginator(_embeds(3))
    p._move(-1)
    assert p.page == 2


def test_next_wraps_from_last_to_first() -> None:
    p = Paginator(_embeds(3))
    p._page = 2
    p._move(1)
    assert p.page == 0
```

- [ ] **Step 2: Write failing confirm view tests**

Create `tests/test_confirm_view.py`:

```python
from __future__ import annotations

import discord

from manhwa_bot.ui.confirm_view import ConfirmView


def test_confirm_view_uses_v1_button_labels_and_styles() -> None:
    view = ConfirmView(author_id=123)
    buttons = [child for child in view.children if isinstance(child, discord.ui.Button)]

    assert [(button.label, button.style) for button in buttons] == [
        ("Confirm", discord.ButtonStyle.green),
        ("Cancel", discord.ButtonStyle.red),
    ]


def test_confirm_prompt_embed_defaults_to_v1_shape() -> None:
    embed = ConfirmView.prompt_embed("Continue?")

    assert embed.title == "Are you sure?"
    assert embed.description == "Continue?"
    assert embed.colour == discord.Colour.orange()
```

- [ ] **Step 3: Run tests to verify red**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_paginator.py tests/test_confirm_view.py -q
```

Expected: failures for old paginator labels/styles and old confirm labels.

- [ ] **Step 4: Implement minimal shared UI changes**

In `Paginator`, make row 0 buttons v1 labels/styles, add `_move(delta: int)`, wrap prev/next, make first/last always jump to boundaries, and make stop edit the message with `view=None`.

In `ConfirmView`, change button labels/styles and add:

```python
@staticmethod
def prompt_embed(
    prompt_message: str | None = None,
    *,
    prompt_title: str = "Are you sure?",
) -> discord.Embed:
    return discord.Embed(
        title=prompt_title,
        description=prompt_message,
        colour=discord.Colour.orange(),
    )
```

- [ ] **Step 5: Run tests to verify green**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_paginator.py tests/test_confirm_view.py -q
```

Expected: all tests pass.

---

### Task 2: Slash Command Metadata Parity

**Files:**
- Create: `tests/test_command_metadata_parity.py`
- Modify: `src/manhwa_bot/cogs/tracking.py`
- Modify: `src/manhwa_bot/cogs/subscriptions.py`
- Modify: `src/manhwa_bot/cogs/bookmarks.py`
- Modify: `src/manhwa_bot/cogs/catalog.py`
- Modify: `src/manhwa_bot/cogs/general.py`
- Modify: `src/manhwa_bot/cogs/settings.py`

- [ ] **Step 1: Write failing metadata tests**

Create tests that instantiate or inspect cog class command objects and assert v1 descriptions. Include `@app_commands.rename` visible names for `manga`, `manhwa`, `scanlator`, `global`, `from`, `manga_url`, and `chapter` where discord.py exposes parameter metadata.

- [ ] **Step 2: Run metadata tests to verify red**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_command_metadata_parity.py -q
```

Expected: failures for the currently divergent descriptions and missing renames.

- [ ] **Step 3: Update command decorators**

Change only public metadata and renames. Leave `/get_lost_manga` untouched.

- [ ] **Step 4: Run metadata tests to verify green**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_command_metadata_parity.py -q
```

Expected: pass.

---

### Task 3: Search And Info Action View Parity

**Files:**
- Create: `tests/test_subscribe_view.py`
- Modify: `src/manhwa_bot/ui/subscribe_view.py`
- Modify: `src/manhwa_bot/cogs/catalog.py`
- Modify: `src/manhwa_bot/formatting.py`

- [ ] **Step 1: Write failing component tests**

Assert `SubscribeView` renders `Track and Subscribe`, `More Info`, and `Bookmark` in v1 styles with v1 emojis.

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_subscribe_view.py -q
```

- [ ] **Step 3: Implement v1 button labels and callbacks**

Use v2 stores and crawler calls inside callbacks. Preserve v1 public responses: `Subscribed to Series`, `Bookmarked!`, and `Website is disabled` / permissions errors where applicable.

- [ ] **Step 4: Update catalog call sites**

Use the v1 action view below `/search` and `/info`, with v1 paginator controls inherited from Task 1.

- [ ] **Step 5: Run focused catalog/UI tests**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_subscribe_view.py tests/test_paginator.py -q
```

---

### Task 4: Bookmark View Parity

**Files:**
- Create: `tests/test_bookmark_view_parity.py`
- Modify: `src/manhwa_bot/ui/bookmark_view.py`
- Modify: `src/manhwa_bot/cogs/bookmarks.py`
- Modify: `src/manhwa_bot/formatting.py`

- [ ] **Step 1: Write failing bookmark view tests**

Assert visual mode default, v1 navigation row, visual controls (`Update`, `Search`, `Delete`), folder select, and text mode sort select.

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_bookmark_view_parity.py -q
```

- [ ] **Step 3: Implement static component parity**

Rebuild bookmark view components to match v1 rows and labels before mutating behavior.

- [ ] **Step 4: Implement view mode, sort, folder, search, update, and delete callbacks**

Keep crawler-backed chapter fetching and store writes. Use v1 success and error embed text.

- [ ] **Step 5: Run bookmark tests**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_bookmark_view_parity.py tests/test_bookmark_auto_subscribe.py -q
```

---

### Task 5: Settings View Parity

**Files:**
- Create: `tests/test_settings_view_parity.py`
- Modify: `src/manhwa_bot/ui/settings_view.py`
- Modify: `src/manhwa_bot/cogs/settings.py`

- [ ] **Step 1: Write failing settings view tests**

Assert main select labels, boolean select labels, channel/role select placeholders, and buttons: `Save`, `Cancel`, `Delete Mode: Off`, `Delete config`.

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_settings_view_parity.py -q
```

- [ ] **Step 3: Implement settings UI labels and flow**

Keep v2 persistence and warnings. Prefer v1 text where user-visible wording conflicts.

- [ ] **Step 4: Run settings tests**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_settings_view_parity.py -q
```

---

### Task 6: Final Focused Verification

**Files:**
- No new source files expected.

- [ ] **Step 1: Run all parity-focused tests**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest tests/test_paginator.py tests/test_confirm_view.py tests/test_command_metadata_parity.py tests/test_subscribe_view.py tests/test_bookmark_view_parity.py tests/test_settings_view_parity.py -q
```

- [ ] **Step 2: Run broader tests if shared modules changed**

Run:

```powershell
& '.venv\Scripts\python.exe' -m pytest -q
```

- [ ] **Step 3: Run lint/format checks**

Run:

```powershell
& '.venv\Scripts\python.exe' -m ruff format .
& '.venv\Scripts\python.exe' -m ruff check .
```

- [ ] **Step 4: Review git diff**

Run:

```powershell
git diff --stat
git diff -- src tests
```

Expected: only v1 command parity files changed, `/get_lost_manga` behavior unchanged.
