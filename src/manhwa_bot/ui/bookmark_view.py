"""BookmarkView — paginated visual/text view for the user's bookmarks."""

from __future__ import annotations

import logging
from typing import Any, Literal

import discord

from ..db.bookmarks import Bookmark, BookmarkStore
from ..db.tracked import TrackedStore

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


def _folder_colour(folder: str) -> discord.Colour:
    f = folder.lower()
    if "completed" in f:
        return discord.Colour.blue()
    if "dropped" in f:
        return discord.Colour.red()
    if "hold" in f:
        return discord.Colour.orange()
    if "plan" in f:
        return discord.Colour.greyple()
    return discord.Colour.green()


def _build_visual_embed(
    bm: Bookmark,
    *,
    title: str,
    series_url: str,
    cover_url: str | None,
    index: int,
    total: int,
    tracked_in_guild: bool = True,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Bookmark: {title}",
        url=series_url or None,
        colour=_folder_colour(bm.folder),
    )
    embed.add_field(name="Folder", value=bm.folder, inline=True)
    embed.add_field(
        name="Last read",
        value=bm.last_read_chapter or "—",
        inline=True,
    )
    embed.add_field(name="Website", value=bm.website_key, inline=True)
    if not tracked_in_guild:
        embed.add_field(
            name="⚠️ Not tracked",
            value=(
                "This manga is not tracked in this server, so you will not be notified "
                "for updates unless it is tracked."
            ),
            inline=False,
        )
    if cover_url:
        embed.set_thumbnail(url=cover_url)
    embed.set_footer(text=f"Bookmark {index + 1}/{total}")
    return embed


def _build_text_embed(
    items: list[tuple[Bookmark, str]],
    *,
    page: int,
    total_pages: int,
    folder_label: str,
) -> discord.Embed:
    """Render up to ``_TEXT_PAGE_SIZE`` bookmarks as a text list.

    ``items`` is a list of ``(bookmark, display_title)`` pairs.
    """
    lines: list[str] = []
    for bm, display_title in items:
        last = bm.last_read_chapter or "—"
        lines.append(f"**{display_title}** · `{bm.folder}` · last: {last}")
    embed = discord.Embed(
        title="Your bookmarks",
        description="\n".join(lines) if lines else "No bookmarks in this folder.",
        colour=discord.Colour.blurple(),
    )
    embed.set_footer(text=f"{folder_label} • Page {page + 1}/{max(1, total_pages)}")
    return embed


class _SetLastReadModal(discord.ui.Modal, title="Set last read chapter"):
    chapter_index: discord.ui.TextInput = discord.ui.TextInput(
        label="Chapter index (0-based)",
        placeholder="e.g. 42",
        required=True,
        max_length=10,
    )

    def __init__(self, view: BookmarkView, current_bm: Bookmark) -> None:
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
        except Exception as exc:  # crawler error
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


class BookmarkView(discord.ui.View):
    """Interactive bookmark browser.

    Visual mode shows one bookmark with cover + metadata; text mode lists
    ten per page. A folder dropdown re-filters in place. The "Set last read"
    button opens a modal that calls the crawler to validate the chapter index.
    """

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
    ) -> None:
        super().__init__(timeout=timeout)
        self._all = list(bookmarks)
        self._store = store
        self._tracked = tracked
        self._crawler = crawler
        self._invoker_id = invoker_id
        self._guild_id = guild_id
        self._current_folder = current_folder
        self._mode: Literal["visual", "text"] = "visual"
        # title / series_url / cover_url cache: (website_key, url_name) -> dict
        self._meta: dict[tuple[str, str], dict[str, Any]] = {}
        self._filtered = self._apply_folder_filter()
        self._index = max(0, min(index, max(0, len(self._filtered) - 1)))

    # -- helpers ---------------------------------------------------------

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
        """Fetch chapters for a bookmark via the crawler."""
        meta = await self._meta_for(bm)
        identifier = meta["series_url"] or bm.url_name
        data = await self._crawler.request_with_progress(
            "info", website_key=bm.website_key, url=identifier, on_progress=None
        )
        return list(data.get("chapters") or data.get("latest_chapters") or [])

    # -- discord.ui.View API --------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                "Only the person who ran this command can navigate.", ephemeral=True
            )
            return False
        return True

    # -- rendering ------------------------------------------------------

    async def initial_embed(self) -> discord.Embed:
        await self._rebuild_components()
        return await self._current_embed()

    async def _current_embed(self) -> discord.Embed:
        if not self._filtered:
            label = self._current_folder or "All"
            return discord.Embed(
                title="No bookmarks",
                description=f"No bookmarks in **{label}**.",
                colour=discord.Colour.greyple(),
            )

        if self._mode == "visual":
            bm = self._filtered[self._index]
            meta = await self._meta_for(bm)
            return _build_visual_embed(
                bm,
                title=meta["title"],
                series_url=meta["series_url"],
                cover_url=meta["cover_url"],
                index=self._index,
                total=len(self._filtered),
                tracked_in_guild=await self._is_tracked_in_context(bm),
            )

        # text mode
        page = self._index // _TEXT_PAGE_SIZE
        total_pages = max(1, (len(self._filtered) + _TEXT_PAGE_SIZE - 1) // _TEXT_PAGE_SIZE)
        start = page * _TEXT_PAGE_SIZE
        chunk = self._filtered[start : start + _TEXT_PAGE_SIZE]
        items: list[tuple[Bookmark, str]] = []
        for bm in chunk:
            meta = await self._meta_for(bm)
            items.append((bm, meta["title"]))
        return _build_text_embed(
            items,
            page=page,
            total_pages=total_pages,
            folder_label=self._current_folder or "All",
        )

    async def _rebuild_components(self) -> None:
        self.clear_items()

        # Row 0: v1 navigation buttons.
        nav_buttons = [
            ("⏮️", discord.ButtonStyle.blurple, self._on_first),
            ("⬅️", discord.ButtonStyle.blurple, self._on_prev),
            ("⏹️", discord.ButtonStyle.red, self._on_stop),
            ("➡️", discord.ButtonStyle.blurple, self._on_next),
            ("⏭️", discord.ButtonStyle.blurple, self._on_last),
        ]
        for label, style, callback in nav_buttons:
            btn = discord.ui.Button(label=label, style=style, row=0)
            btn.callback = callback  # type: ignore[assignment]
            self.add_item(btn)

        if not self._filtered:
            return

        if self._mode == "text":
            sort_select = discord.ui.Select(
                placeholder="Select sort type.",
                min_values=1,
                max_values=1,
                row=1,
                options=[
                    discord.SelectOption(label="Last Updated", value="last_updated"),
                    discord.SelectOption(label="Title", value="title"),
                ],
            )
            sort_select.callback = self._on_sort_select  # type: ignore[assignment]
            self.add_item(sort_select)

        view_select = discord.ui.Select(
            placeholder="Select view type.",
            min_values=1,
            max_values=1,
            row=2,
            options=[
                discord.SelectOption(
                    label="Visual",
                    value="visual",
                    default=self._mode == "visual",
                ),
                discord.SelectOption(
                    label="Text",
                    value="text",
                    default=self._mode == "text",
                ),
            ],
        )
        view_select.callback = self._on_view_select  # type: ignore[assignment]
        self.add_item(view_select)

        # Row 3: visual-only actions.
        if self._mode == "visual":
            self.add_item(
                discord.ui.Button(
                    label="\u200b",
                    style=discord.ButtonStyle.grey,
                    disabled=True,
                    row=3,
                )
            )
            update_btn = discord.ui.Button(label="Update", style=discord.ButtonStyle.blurple, row=3)
            update_btn.callback = self._on_set_last_read  # type: ignore[assignment]
            self.add_item(update_btn)

            search_btn = discord.ui.Button(label="Search", style=discord.ButtonStyle.blurple, row=3)
            search_btn.callback = self._on_search  # type: ignore[assignment]
            self.add_item(search_btn)

            delete_btn = discord.ui.Button(label="Delete", style=discord.ButtonStyle.red, row=3)
            delete_btn.callback = self._on_delete  # type: ignore[assignment]
            self.add_item(delete_btn)

            self.add_item(
                discord.ui.Button(
                    label="\u200b",
                    style=discord.ButtonStyle.grey,
                    disabled=True,
                    row=3,
                )
            )

        folder_select = discord.ui.Select(
            placeholder="Select folder.",
            min_values=1,
            max_values=1,
            row=4,
            options=[
                discord.SelectOption(
                    label="All",
                    value="__all__",
                    default=self._current_folder is None,
                )
            ]
            + [
                discord.SelectOption(label=f, value=f, default=self._current_folder == f)
                for f in BOOKMARK_FOLDERS
            ],
        )
        folder_select.callback = self._on_folder_select  # type: ignore[assignment]
        self.add_item(folder_select)

    # -- callbacks -------------------------------------------------------

    async def _on_folder_select(self, interaction: discord.Interaction) -> None:
        # discord.py exposes the chosen value via interaction.data["values"]
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        choice = values[0] if values else "__all__"
        self._current_folder = None if choice == "__all__" else choice
        self._filtered = self._apply_folder_filter()
        self._index = 0
        await self._rebuild_components()
        embed = await self._current_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_first(self, interaction: discord.Interaction) -> None:
        self._index = 0
        await self._rebuild_components()
        embed = await self._current_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_prev(self, interaction: discord.Interaction) -> None:
        if self._mode == "visual":
            self._index = (self._index - 1) % len(self._filtered)
        else:
            self._index = (self._index - _TEXT_PAGE_SIZE) % len(self._filtered)
        await self._rebuild_components()
        embed = await self._current_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_stop(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)
        self.stop()

    async def _on_next(self, interaction: discord.Interaction) -> None:
        if self._mode == "visual":
            self._index = (self._index + 1) % len(self._filtered)
        else:
            self._index = (self._index + _TEXT_PAGE_SIZE) % len(self._filtered)
        await self._rebuild_components()
        embed = await self._current_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_last(self, interaction: discord.Interaction) -> None:
        self._index = len(self._filtered) - 1
        await self._rebuild_components()
        embed = await self._current_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_view_select(self, interaction: discord.Interaction) -> None:
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        self._mode = "text" if values and values[0] == "text" else "visual"
        # Snap index to a valid value for the new mode.
        if self._mode == "text":
            self._index = (self._index // _TEXT_PAGE_SIZE) * _TEXT_PAGE_SIZE
        await self._rebuild_components()
        embed = await self._current_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_sort_select(self, interaction: discord.Interaction) -> None:
        values = (interaction.data or {}).get("values") or []  # type: ignore[union-attr]
        if values and values[0] == "title":
            self._filtered = sorted(self._filtered, key=lambda bm: bm.url_name.lower())
        else:
            self._filtered = sorted(self._filtered, key=lambda bm: bm.updated_at, reverse=True)
        self._index = 0
        await self._rebuild_components()
        embed = await self._current_embed()
        await interaction.response.edit_message(embed=embed, view=self)

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
        """Mutate the current bookmark in-place and re-render after a modal submit."""
        if not self._filtered:
            return
        bm = self._filtered[self._index]
        from dataclasses import replace

        new_bm = replace(bm, last_read_chapter=chapter_text, last_read_index=chapter_index)
        self._filtered[self._index] = new_bm
        # Update master list too so a re-filter doesn't lose the change.
        for i, all_bm in enumerate(self._all):
            if (
                all_bm.user_id == bm.user_id
                and all_bm.website_key == bm.website_key
                and all_bm.url_name == bm.url_name
            ):
                self._all[i] = new_bm
                break
        await self._rebuild_components()
        embed = await self._current_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True  # type: ignore[attr-defined]
