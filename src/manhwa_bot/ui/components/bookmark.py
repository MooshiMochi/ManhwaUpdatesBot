"""Bookmark layouts: single-bookmark display, update-ack, and browser view."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Literal

import discord

from ...db.bookmarks import Bookmark, BookmarkStore
from ...db.tracked import TrackedStore
from .. import emojis
from .base import (
    BaseLayoutView,
    folder_accent,
    footer_section,
    hero_cover_gallery,
    large_separator,
    safe_truncate,
    small_separator,
)

_log = logging.getLogger(__name__)

BOOKMARK_FOLDERS: tuple[str, ...] = (
    "Reading",
    "On Hold",
    "Plan to Read",
    "Re-Reading",
    "Completed",
    "Dropped",
)

_TEXT_PAGE_SIZE = 10


# ---------------------------------------------------------------------------
# Static factory: rich bookmark detail (used by /bookmark new success message)
# ---------------------------------------------------------------------------


def build_bookmark_detail_view(
    *,
    title: str,
    series_url: str,
    website_key: str,
    cover_url: str | None,
    scanlator_base_url: str | None,
    last_read_chapter: str,
    next_chapter: str | None,
    folder: str,
    available_chapters_label: str,
    chapter_count: int,
    status: str,
    is_completed: bool,
    bot: discord.Client | None = None,
    invoker_id: int | None = None,
    extra_action_row: discord.ui.ActionRow | None = None,
) -> discord.ui.LayoutView:
    """Hero `/bookmark new`/`view` single-card layout."""
    if next_chapter:
        next_text = next_chapter
    elif is_completed:
        next_text = f"`None — manhwa is {status.lower() or 'completed'}`"
    else:
        next_text = "`Wait for updates`"

    available = (
        f"{available_chapters_label} ({chapter_count})" if chapter_count else "`Wait for updates`"
    )

    scanlator_link = (
        f"[{website_key.title()}]({scanlator_base_url})"
        if scanlator_base_url
        else website_key.title()
    )
    header_block = f"# 🔖  [{title}]({series_url})" if series_url else f"# 🔖  {title}"
    details_block = (
        f"**Scanlator:** {scanlator_link}\n"
        f"**Folder:** `{folder}`\n"
        f"**Status:** `{status}`\n"
        f"**Last Read:** {last_read_chapter}\n"
        f"**Next Chapter:** {next_text}\n"
        f"**Available Chapters:** Up to {available}"
    )

    container = discord.ui.Container(accent_colour=folder_accent(folder))
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header_block))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(details_block))
    container.add_item(small_separator())
    container.add_item(footer_section(bot))
    if extra_action_row is not None:
        container.add_item(small_separator())
        container.add_item(extra_action_row)

    view = BaseLayoutView(invoker_id=invoker_id, timeout=None, lock=invoker_id is not None)
    view.add_item(container)
    return view


def build_bookmark_update_success_view(
    *,
    moved_folder: str | None,
    new_chapter_label: str | None,
    auto_subscribed_title: str | None,
    should_track: bool,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Acknowledgement view for `/bookmark update`."""
    lines: list[str] = ["Bookmark updated successfully!"]
    if moved_folder:
        lines.append(f"\n• Moved bookmark to **{moved_folder}**")
    if new_chapter_label:
        lines.append(f"\n• Updated last read chapter to **{new_chapter_label}**")
    if auto_subscribed_title:
        lines.append(f"\n\n📨  You have been subscribed to updates for **{auto_subscribed_title}**")
    elif should_track:
        lines.append(
            "\n\n-# *You should consider tracking and subscribing to this manga to get updates.*"
        )
    body = "".join(lines)

    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.CHECK}  Bookmark updated"),
        small_separator(),
        discord.ui.TextDisplay(body),
        small_separator(),
        footer_section(bot),
        accent_colour=discord.Colour.green(),
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


# ---------------------------------------------------------------------------
# BookmarkBrowserView — replaces ui/bookmark_view.py BookmarkView
# ---------------------------------------------------------------------------


def _visual_container(
    bm: Bookmark,
    *,
    title: str,
    series_url: str,
    cover_url: str | None,
    index: int,
    total: int,
    tracked_in_guild: bool,
) -> discord.ui.Container:
    header_block = f"# 🔖  [{title}]({series_url})" if series_url else f"# 🔖  {title}"
    details_block = (
        f"**Folder:** `{bm.folder}`\n"
        f"**Website:** `{bm.website_key}`\n"
        f"**Last Read:** {bm.last_read_chapter or '—'}"
    )

    container = discord.ui.Container(accent_colour=folder_accent(bm.folder))
    gallery = hero_cover_gallery(cover_url)
    if gallery is not None:
        container.add_item(gallery)
    container.add_item(discord.ui.TextDisplay(header_block))
    container.add_item(small_separator())
    container.add_item(discord.ui.TextDisplay(details_block))
    if not tracked_in_guild:
        container.add_item(small_separator())
        container.add_item(
            discord.ui.TextDisplay(
                f"{emojis.WARNING} **Not tracked here** — you won't get notifications "
                "until an admin runs `/track new` for this series."
            )
        )
    container.add_item(small_separator())
    container.add_item(footer_section(None, extra=f"Bookmark {index + 1}/{total}"))
    return container


def _text_container(
    items: list[tuple[Bookmark, str]],
    *,
    page: int,
    total_pages: int,
    folder_label: str,
) -> discord.ui.Container:
    lines: list[str] = []
    for bm, display_title in items:
        last = bm.last_read_chapter or "—"
        lines.append(f"**{display_title}** · `{bm.folder}` · last: {last}")

    body = "\n".join(lines) if lines else "No bookmarks in this folder."
    container = discord.ui.Container(
        discord.ui.TextDisplay("## 🔖  Your bookmarks"),
        small_separator(),
        discord.ui.TextDisplay(safe_truncate(body, 3500)),
        small_separator(),
        footer_section(None, extra=f"{folder_label} • Page {page + 1}/{max(1, total_pages)}"),
        accent_colour=discord.Colour.blurple(),
    )
    return container


class _SetLastReadModal(discord.ui.Modal, title="Set last read chapter"):
    chapter_index: discord.ui.TextInput = discord.ui.TextInput(
        label="Chapter index (0-based)",
        placeholder="e.g. 42",
        required=True,
        max_length=10,
    )

    def __init__(self, view: BookmarkBrowserView, current_bm: Bookmark) -> None:
        super().__init__()
        self._view = view
        self._bm = current_bm
        if current_bm.last_read_index is not None:
            self.chapter_index.default = str(current_bm.last_read_index)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = (self.chapter_index.value or "").strip()
        try:
            idx = int(raw)
        except ValueError:
            await interaction.response.send_message(
                "Chapter index must be an integer.", ephemeral=True
            )
            return
        if idx < 0:
            await interaction.response.send_message("Chapter index must be ≥ 0.", ephemeral=True)
            return

        try:
            chapters = await self._view._fetch_chapters(self._bm)
        except Exception as exc:
            await interaction.response.send_message(
                f"Couldn't fetch chapters: {exc}", ephemeral=True
            )
            return

        if not chapters or idx >= len(chapters):
            await interaction.response.send_message(
                f"Chapter index out of range (0 - {max(0, len(chapters) - 1)}).",
                ephemeral=True,
            )
            return

        ch = chapters[idx]
        chapter_text = ch.get("chapter") or ch.get("chapter_number") or f"#{ch.get('index', idx)}"
        await self._view._store.update_last_read(
            self._bm.user_id,
            self._bm.website_key,
            self._bm.url_name,
            chapter_text=chapter_text,
            chapter_index=idx,
        )
        await self._view._refresh_current(interaction, chapter_text=chapter_text, chapter_index=idx)


class BookmarkBrowserView(BaseLayoutView):
    """V2 bookmark browser. Visual + text modes, folder filter, set-last-read modal."""

    def __init__(
        self,
        bookmarks: list[Bookmark],
        *,
        store: BookmarkStore,
        tracked: TrackedStore,
        crawler: Any,
        invoker_id: int,
        guild_id: int | None = None,
        current_folder: str | None = None,
        index: int = 0,
        timeout: float = 300.0,
        bot: discord.Client | None = None,
    ) -> None:
        super().__init__(invoker_id=invoker_id, timeout=timeout)
        self._all = list(bookmarks)
        self._store = store
        self._tracked = tracked
        self._crawler = crawler
        self._guild_id = guild_id
        self._current_folder = current_folder
        self._mode: Literal["visual", "text"] = "visual"
        self._bot = bot
        self._meta: dict[tuple[str, str], dict[str, Any]] = {}
        self._filtered = self._apply_folder_filter()
        self._index = max(0, min(index, max(0, len(self._filtered) - 1)))

    # ---- public ---------------------------------------------------------

    async def initial_render(self) -> None:
        """Populate the view with its first render (must be awaited before send)."""
        await self._rebuild()

    # ---- helpers --------------------------------------------------------

    def _apply_folder_filter(self) -> list[Bookmark]:
        if self._current_folder is None:
            return list(self._all)
        return [b for b in self._all if b.folder == self._current_folder]

    async def _meta_for(self, bm: Bookmark) -> dict[str, Any]:
        key = (bm.website_key, bm.url_name)
        if key in self._meta:
            return self._meta[key]
        title = bm.url_name
        series_url = ""
        cover_url: str | None = None
        try:
            tracked = await self._tracked.find(bm.website_key, bm.url_name)
        except Exception:
            tracked = None
        if tracked is not None:
            title = tracked.title
            series_url = tracked.series_url
            cover_url = tracked.cover_url
        meta = {"title": title, "series_url": series_url, "cover_url": cover_url}
        self._meta[key] = meta
        return meta

    async def _is_tracked_in_context(self, bm: Bookmark) -> bool:
        if self._guild_id is None:
            return True
        try:
            rows = await self._tracked.list_guilds_tracking(bm.website_key, bm.url_name)
        except Exception:
            return True
        return any(int(row.guild_id) == int(self._guild_id) for row in rows)

    async def _fetch_chapters(self, bm: Bookmark) -> list[dict]:
        meta = await self._meta_for(bm)
        identifier = meta["series_url"] or bm.url_name
        data = await self._crawler.request_with_progress(
            "info", website_key=bm.website_key, url=identifier, on_progress=None
        )
        return list(data.get("chapters") or data.get("latest_chapters") or [])

    # ---- rendering ------------------------------------------------------

    async def _build_container(self) -> discord.ui.Container:
        if not self._filtered:
            label = self._current_folder or "All"
            return discord.ui.Container(
                discord.ui.TextDisplay("## 🔖  No bookmarks"),
                small_separator(),
                discord.ui.TextDisplay(f"No bookmarks in **{label}**."),
                large_separator(),
                footer_section(self._bot),
                accent_colour=discord.Colour.greyple(),
            )

        if self._mode == "visual":
            bm = self._filtered[self._index]
            meta = await self._meta_for(bm)
            tracked = await self._is_tracked_in_context(bm)
            return _visual_container(
                bm,
                title=meta["title"],
                series_url=meta["series_url"],
                cover_url=meta["cover_url"],
                index=self._index,
                total=len(self._filtered),
                tracked_in_guild=tracked,
            )

        page = self._index // _TEXT_PAGE_SIZE
        total_pages = max(1, (len(self._filtered) + _TEXT_PAGE_SIZE - 1) // _TEXT_PAGE_SIZE)
        start = page * _TEXT_PAGE_SIZE
        chunk = self._filtered[start : start + _TEXT_PAGE_SIZE]
        items: list[tuple[Bookmark, str]] = []
        for bm in chunk:
            meta = await self._meta_for(bm)
            items.append((bm, meta["title"]))
        return _text_container(
            items,
            page=page,
            total_pages=total_pages,
            folder_label=self._current_folder or "All",
        )

    async def _rebuild(self) -> None:
        """Reconstruct all top-level children of this view."""
        self.clear_items()
        container = await self._build_container()

        # Nav row (always)
        nav_row = discord.ui.ActionRow()
        for label, style, target in (
            ("⏮️", discord.ButtonStyle.blurple, "first"),
            ("⬅️", discord.ButtonStyle.blurple, "prev"),
            ("⏹️", discord.ButtonStyle.red, "stop"),
            ("➡️", discord.ButtonStyle.blurple, "next"),
            ("⏭️", discord.ButtonStyle.blurple, "last"),
        ):
            btn = discord.ui.Button(label=label, style=style)
            btn.callback = self._make_nav_callback(target)  # type: ignore[assignment]
            nav_row.add_item(btn)
        container.add_item(small_separator())
        container.add_item(nav_row)
        self.add_item(container)

        if not self._filtered:
            return

        # View-mode select row
        view_row = discord.ui.ActionRow()
        view_select = discord.ui.Select(
            placeholder="Select view type.",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Visual", value="visual", default=self._mode == "visual"
                ),
                discord.SelectOption(label="Text", value="text", default=self._mode == "text"),
            ],
        )
        view_select.callback = self._on_view_select  # type: ignore[assignment]
        view_row.add_item(view_select)
        self.add_item(view_row)

        # Text-mode-only sort select
        if self._mode == "text":
            sort_row = discord.ui.ActionRow()
            sort_select = discord.ui.Select(
                placeholder="Sort by…",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(label="Last Updated", value="last_updated"),
                    discord.SelectOption(label="Title", value="title"),
                ],
            )
            sort_select.callback = self._on_sort_select  # type: ignore[assignment]
            sort_row.add_item(sort_select)
            self.add_item(sort_row)

        # Visual-mode action buttons
        if self._mode == "visual":
            action_row = discord.ui.ActionRow()
            update_btn = discord.ui.Button(
                label="Update", emoji="✏️", style=discord.ButtonStyle.blurple
            )
            update_btn.callback = self._on_set_last_read  # type: ignore[assignment]
            action_row.add_item(update_btn)
            search_btn = discord.ui.Button(
                label="Search", emoji="🔍", style=discord.ButtonStyle.blurple
            )
            search_btn.callback = self._on_search  # type: ignore[assignment]
            action_row.add_item(search_btn)
            delete_btn = discord.ui.Button(label="Delete", emoji="🗑️", style=discord.ButtonStyle.red)
            delete_btn.callback = self._on_delete  # type: ignore[assignment]
            action_row.add_item(delete_btn)
            container.add_item(small_separator())
            container.add_item(action_row)

        # Folder filter
        folder_row = discord.ui.ActionRow()
        folder_select = discord.ui.Select(
            placeholder="Filter by folder.",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="All", value="__all__", default=self._current_folder is None
                )
            ]
            + [
                discord.SelectOption(label=f, value=f, default=self._current_folder == f)
                for f in BOOKMARK_FOLDERS
            ],
        )
        folder_select.callback = self._on_folder_select  # type: ignore[assignment]
        folder_row.add_item(folder_select)
        self.add_item(folder_row)

    # ---- callbacks ------------------------------------------------------

    def _make_nav_callback(self, target: str):
        async def cb(interaction: discord.Interaction) -> None:
            if not self._filtered:
                await interaction.response.defer()
                return
            if target == "first":
                self._index = 0
            elif target == "prev":
                step = 1 if self._mode == "visual" else _TEXT_PAGE_SIZE
                self._index = (self._index - step) % len(self._filtered)
            elif target == "next":
                step = 1 if self._mode == "visual" else _TEXT_PAGE_SIZE
                self._index = (self._index + step) % len(self._filtered)
            elif target == "last":
                self._index = len(self._filtered) - 1
            elif target == "stop":
                await interaction.response.edit_message(view=None)
                self.stop()
                return
            await self._rebuild()
            await interaction.response.edit_message(view=self)

        return cb

    async def _on_view_select(self, interaction: discord.Interaction) -> None:
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        self._mode = "text" if values and values[0] == "text" else "visual"
        if self._mode == "text":
            self._index = (self._index // _TEXT_PAGE_SIZE) * _TEXT_PAGE_SIZE
        await self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_sort_select(self, interaction: discord.Interaction) -> None:
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        if values and values[0] == "title":
            self._filtered = sorted(self._filtered, key=lambda bm: bm.url_name.lower())
        else:
            self._filtered = sorted(self._filtered, key=lambda bm: bm.updated_at, reverse=True)
        self._index = 0
        await self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_folder_select(self, interaction: discord.Interaction) -> None:
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        choice = values[0] if values else "__all__"
        self._current_folder = None if choice == "__all__" else choice
        self._filtered = self._apply_folder_filter()
        self._index = 0
        await self._rebuild()
        await interaction.response.edit_message(view=self)

    async def _on_set_last_read(self, interaction: discord.Interaction) -> None:
        if not self._filtered:
            await interaction.response.send_message("No bookmark selected.", ephemeral=True)
            return
        bm = self._filtered[self._index]
        await interaction.response.send_modal(_SetLastReadModal(self, bm))

    async def _on_search(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Bookmark search is not available in this view yet.", ephemeral=True
        )

    async def _on_delete(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "Use `/bookmark delete` to delete this bookmark.", ephemeral=True
        )

    async def _refresh_current(
        self,
        interaction: discord.Interaction,
        *,
        chapter_text: str,
        chapter_index: int,
    ) -> None:
        if not self._filtered:
            return
        bm = self._filtered[self._index]
        new_bm = replace(bm, last_read_chapter=chapter_text, last_read_index=chapter_index)
        self._filtered[self._index] = new_bm
        for i, all_bm in enumerate(self._all):
            if (
                all_bm.user_id == bm.user_id
                and all_bm.website_key == bm.website_key
                and all_bm.url_name == bm.url_name
            ):
                self._all[i] = new_bm
                break
        await self._rebuild()
        await interaction.response.edit_message(view=self)


# ---------------------------------------------------------------------------
# "View Bookmark" action row used by `/bookmark new` success message
# ---------------------------------------------------------------------------


class _ViewBookmarkButton(discord.ui.Button):
    """Single-button row factory consumer; opens a BookmarkBrowserView."""

    def __init__(self, factory):
        super().__init__(label="View Bookmark", emoji="🔖", style=discord.ButtonStyle.blurple)
        self._factory = factory

    async def callback(self, interaction: discord.Interaction) -> None:  # type: ignore[override]
        try:
            view = await self._factory()
        except Exception as exc:
            _log.exception("View Bookmark button factory failed")
            await interaction.response.send_message(
                f"Couldn't open bookmark view: {exc}", ephemeral=True
            )
            return
        await interaction.response.send_message(view=view, ephemeral=True)


def view_bookmark_action_row(factory) -> discord.ui.ActionRow:
    row = discord.ui.ActionRow()
    row.add_item(_ViewBookmarkButton(factory))
    return row
