"""Persistent DynamicItem buttons for the chapter update notification view."""

from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import discord

from ...crawler.chapter import Chapter
from ...db.bookmarks import Bookmark, BookmarkStore
from ...db.dm_settings import DmSettingsStore
from ...db.guild_settings import GuildSettingsStore
from ...db.notification_actions import NotificationActionContext, NotificationActionContextStore
from ...db.notification_button_state import MarkReadToggleStore
from ...db.subscriptions import SubscriptionStore
from ...db.tracked import TrackedSeries, TrackedStore
from .. import emojis
from .base import BaseLayoutView, safe_truncate, severity_accent, small_separator

_log = logging.getLogger(__name__)

# Canonical key order for storage + UI rendering.
UPDATE_BUTTON_KEYS: tuple[str, ...] = (
    "mark_read",
    "bookmark",
    "subscribe",
    "open_chapter",
)
ALL_UPDATE_BUTTONS: frozenset[str] = frozenset(UPDATE_BUTTON_KEYS)

# (label, emoji, description) — used by settings select + buttons.
UPDATE_BUTTON_LABELS: dict[str, tuple[str, str, str]] = {
    "mark_read": (
        "Mark Read",
        "✅",
        "Marks the chapter as read in your bookmark.",
    ),
    "bookmark": (
        "Bookmark",
        "🔖",
        "Adds this series to your Reading bookmarks.",
    ),
    "subscribe": (
        "Subscribe",
        "🔔",
        "Toggles your subscription for this series.",
    ),
    "open_chapter": (
        "Last Read Chapter",
        "📖",
        "Shows your last read chapter for this series.",
    ),
}

# Slug guard — website_key and url_name come from the schema and must never
# contain a literal `:` (custom_id delimiter).
_SLUG_RE = re.compile(r"^[^:]+$")


def _assert_slug(value: str, *, field: str) -> str:
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(f"{field}={value!r} contains a ':' which breaks custom_id parsing")
    return value


def _series_link(tracked: TrackedSeries | None, url_name: str) -> str:
    if tracked is None:
        return f"`{url_name}`"
    title = tracked.title or url_name
    return f"[{title}]({tracked.series_url})"


def _chapter_markdown(label: str, url: str | None) -> str:
    return f"[{label}]({url})" if url else label


async def _resolve_mark_read_chapter(
    *,
    client: object,
    tracked: TrackedSeries | None,
    website_key: str,
    url_name: str,
    chapter_index: int,
) -> tuple[str, str]:
    crawler = getattr(client, "crawler", None)
    identifier = tracked.series_url if tracked is not None else url_name
    if crawler is not None:
        try:
            data = await crawler.request("chapters", website_key=website_key, url=identifier)
            chapters = Chapter.list_from_payload(data)
        except Exception:
            _log.exception(
                "failed to resolve notification chapter for %s:%s", website_key, url_name
            )
        else:
            chapter = next(
                (chapter for chapter in chapters if chapter.index == chapter_index),
                chapters[chapter_index] if 0 <= chapter_index < len(chapters) else None,
            )
            if chapter is not None:
                return chapter.name, str(chapter)

    if tracked is not None and tracked.last_chapter_text:
        return tracked.last_chapter_text, _chapter_markdown(
            tracked.last_chapter_text,
            tracked.last_chapter_url,
        )

    return "selected chapter", "the selected chapter"


def _ack_view(
    *,
    title: str,
    description: str,
    level: str = "success",
) -> discord.ui.LayoutView:
    accent = severity_accent("success" if level == "success" else "warning")
    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {title}"),
        small_separator(),
        discord.ui.TextDisplay(safe_truncate(description, 3800)),
        accent_colour=accent,
    )
    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    return view


async def _send_ack(
    interaction: discord.Interaction,
    *,
    title: str,
    description: str,
    level: str = "success",
) -> None:
    await interaction.followup.send(
        view=_ack_view(title=title, description=description, level=level),
        ephemeral=True,
    )


MARK_READ_TEMPLATE = r"mu:upd:mr:(?P<wk>[^:]+):(?P<un>[^:]+):(?P<idx>-?\d+)"
BOOKMARK_TEMPLATE = r"mu:upd:bm:(?P<wk>[^:]+):(?P<un>[^:]+)"
SUBSCRIBE_TEMPLATE = r"mu:upd:sub:(?P<wk>[^:]+):(?P<un>[^:]+)"
LAST_READ_TEMPLATE = r"mu:upd:lr:(?P<wk>[^:]+):(?P<un>[^:]+)"
COMPACT_MARK_READ_TEMPLATE = r"mu:u:mr:(?P<token>[A-Za-z0-9_-]{1,24})"
COMPACT_BOOKMARK_TEMPLATE = r"mu:u:bm:(?P<token>[A-Za-z0-9_-]{1,24})"
COMPACT_SUBSCRIBE_TEMPLATE = r"mu:u:sub:(?P<token>[A-Za-z0-9_-]{1,24})"
COMPACT_LAST_READ_TEMPLATE = r"mu:u:lr:(?P<token>[A-Za-z0-9_-]{1,24})"


async def _notification_action_context(
    interaction: discord.Interaction,
    token: str,
) -> NotificationActionContext | None:
    context = await NotificationActionContextStore(interaction.client.db).get(token)  # type: ignore[attr-defined]
    if context is not None:
        return context
    await interaction.response.defer(ephemeral=True, thinking=True)
    await _send_ack(
        interaction,
        title="Notification action unavailable",
        description="This notification's action context is no longer available.",
        level="warning",
    )
    return None


class CompactMarkReadButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=COMPACT_MARK_READ_TEMPLATE,
):
    def __init__(self, token: str) -> None:
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["mark_read"][0],
                emoji=UPDATE_BUTTON_LABELS["mark_read"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:u:mr:{token}",
            )
        )
        self.token = token

    @classmethod
    async def from_custom_id(cls, interaction, item, match):  # type: ignore[no-untyped-def]
        del interaction, item
        return cls(match["token"])

    async def callback(self, interaction: discord.Interaction) -> None:
        context = await _notification_action_context(interaction, self.token)
        if context is None:
            return
        legacy = SimpleNamespace(
            website_key=context.website_key,
            url_name=context.url_name,
            chapter_index=context.chapter_index,
        )
        await MarkReadButton.callback(legacy, interaction)  # type: ignore[arg-type]


class CompactBookmarkButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=COMPACT_BOOKMARK_TEMPLATE,
):
    def __init__(self, token: str) -> None:
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["bookmark"][0],
                emoji=UPDATE_BUTTON_LABELS["bookmark"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:u:bm:{token}",
            )
        )
        self.token = token

    @classmethod
    async def from_custom_id(cls, interaction, item, match):  # type: ignore[no-untyped-def]
        del interaction, item
        return cls(match["token"])

    async def callback(self, interaction: discord.Interaction) -> None:
        context = await _notification_action_context(interaction, self.token)
        if context is None:
            return
        legacy = SimpleNamespace(website_key=context.website_key, url_name=context.url_name)
        await BookmarkButton.callback(legacy, interaction)  # type: ignore[arg-type]


class CompactSubscribeToggleButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=COMPACT_SUBSCRIBE_TEMPLATE,
):
    def __init__(self, token: str) -> None:
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["subscribe"][0],
                emoji=UPDATE_BUTTON_LABELS["subscribe"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:u:sub:{token}",
            )
        )
        self.token = token

    @classmethod
    async def from_custom_id(cls, interaction, item, match):  # type: ignore[no-untyped-def]
        del interaction, item
        return cls(match["token"])

    async def callback(self, interaction: discord.Interaction) -> None:
        context = await _notification_action_context(interaction, self.token)
        if context is None:
            return
        legacy = SimpleNamespace(website_key=context.website_key, url_name=context.url_name)
        await SubscribeToggleButton.callback(legacy, interaction)  # type: ignore[arg-type]


class CompactLastReadChapterButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=COMPACT_LAST_READ_TEMPLATE,
):
    def __init__(self, token: str) -> None:
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["open_chapter"][0],
                emoji=UPDATE_BUTTON_LABELS["open_chapter"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:u:lr:{token}",
            )
        )
        self.token = token

    @classmethod
    async def from_custom_id(cls, interaction, item, match):  # type: ignore[no-untyped-def]
        del interaction, item
        return cls(match["token"])

    async def callback(self, interaction: discord.Interaction) -> None:
        context = await _notification_action_context(interaction, self.token)
        if context is None:
            return
        legacy = SimpleNamespace(website_key=context.website_key, url_name=context.url_name)
        await LastReadChapterButton.callback(legacy, interaction)  # type: ignore[arg-type]


async def _resolve_chapter_list(
    *,
    client: object,
    tracked: TrackedSeries | None,
    website_key: str,
    url_name: str,
) -> list[Chapter]:
    """Fetch the crawler's chapter list for a series (empty on any failure)."""
    crawler = getattr(client, "crawler", None)
    if crawler is None:
        return []
    identifier = tracked.series_url if tracked is not None else url_name
    try:
        data = await crawler.request("chapters", website_key=website_key, url=identifier)
    except Exception:
        _log.exception("failed to resolve chapter list for %s:%s", website_key, url_name)
        return []
    return Chapter.list_from_payload(data)


def _locate_chapter(
    chapters: list[Chapter], chapter_index: int
) -> tuple[int | None, Chapter | None]:
    """Find the bookmark's last-read chapter by its ``index`` field, else by position.

    ``last_read_index`` is a chapter ``index`` value for notification-sourced
    bookmarks but a 0-based list position for browser-sourced ones; matching on
    the index field first and falling back to the position handles both, and the
    returned position lets callers derive the *next* chapter to read.
    """
    for position, chapter in enumerate(chapters):
        if chapter.index == chapter_index:
            return position, chapter
    if 0 <= chapter_index < len(chapters):
        return chapter_index, chapters[chapter_index]
    return None, None


def _clicked_chapter_details(
    *,
    chapter: Chapter | None,
    tracked: TrackedSeries | None,
) -> tuple[str, str]:
    if chapter is not None:
        return chapter.name, str(chapter)
    if tracked is not None and tracked.last_chapter_text:
        return tracked.last_chapter_text, _chapter_markdown(
            tracked.last_chapter_text,
            tracked.last_chapter_url,
        )
    return "selected chapter", "the selected chapter"


def _expected_next_chapter(
    chapters: list[Chapter],
    bookmark: Bookmark | None,
) -> tuple[int | None, Chapter | None]:
    if not chapters:
        return None, None
    if bookmark is None or bookmark.last_read_index is None:
        return 0, chapters[0]
    current_position, _ = _locate_chapter(chapters, bookmark.last_read_index)
    if current_position is None or current_position + 1 >= len(chapters):
        return None, None
    next_position = current_position + 1
    return next_position, chapters[next_position]


async def _apply_mark_read(
    *,
    interaction: discord.Interaction,
    store: BookmarkStore,
    toggles: MarkReadToggleStore,
    tracked: TrackedSeries | None,
    website_key: str,
    url_name: str,
    chapter_index: int,
    chapter_text: str,
    chapter_display: str,
    existing: Bookmark | None,
) -> tuple[str, str]:
    await toggles.save_previous(
        user_id=interaction.user.id,
        website_key=website_key,
        url_name=url_name,
        chapter_index=chapter_index,
        bookmark=existing,
    )
    await store.upsert_bookmark(
        user_id=interaction.user.id,
        website_key=website_key,
        url_name=url_name,
        folder=existing.folder if existing else "Subscribed",
        last_read_chapter=chapter_text,
        last_read_index=chapter_index,
    )
    link = _series_link(tracked, url_name)
    description = (
        f"Marked {link} - {chapter_display} as read."
        if existing
        else f"Bookmarked {link} in *Subscribed* and marked {chapter_display} as read."
    )
    return f"{emojis.CHECK}  Marked read", description


class MarkReadConfirmationView(BaseLayoutView):
    """Invoker-locked confirmation for a non-sequential Mark Read action."""

    def __init__(
        self,
        *,
        invoker_id: int,
        website_key: str,
        url_name: str,
        chapter_index: int,
        chapter_text: str,
        chapter_display: str,
        expected_next: Chapter | None,
        bookmark_snapshot: Bookmark | None,
        tracked: TrackedSeries | None,
    ) -> None:
        super().__init__(invoker_id=invoker_id, timeout=120)
        self._website_key = website_key
        self._url_name = url_name
        self._chapter_index = chapter_index
        self._chapter_text = chapter_text
        self._chapter_display = chapter_display
        self._bookmark_snapshot = bookmark_snapshot
        self._tracked = tracked

        if expected_next is not None:
            warning = (
                f"Your next chapter appears to be {expected_next}. "
                f"Mark {chapter_display} as read anyway?"
            )
        else:
            warning = (
                "I couldn't reliably determine your next chapter. "
                f"Mark {chapter_display} as read anyway?"
            )
        warning = f"**Series:** {_series_link(tracked, url_name)}\n\n{warning}"
        proceed = discord.ui.Button(label="Proceed", style=discord.ButtonStyle.success)
        discard = discord.ui.Button(label="Discard", style=discord.ButtonStyle.secondary)
        proceed.callback = self._proceed
        discard.callback = self._discard
        row = discord.ui.ActionRow()
        row.add_item(proceed)
        row.add_item(discard)
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay("## Check reading progress"),
                small_separator(),
                discord.ui.TextDisplay(warning),
                row,
                accent_colour=severity_accent("warning"),
            )
        )

    async def _proceed(self, interaction: discord.Interaction) -> None:
        pool = interaction.client.db  # type: ignore[attr-defined]
        store = BookmarkStore(pool)
        current = await store.get_bookmark(
            interaction.user.id,
            self._website_key,
            self._url_name,
        )
        if current != self._bookmark_snapshot:
            result = _ack_view(
                title="Reading progress changed",
                description=(
                    "Your bookmark changed while this confirmation was open. "
                    "No changes were made; please try again."
                ),
                level="warning",
            )
        else:
            title, description = await _apply_mark_read(
                interaction=interaction,
                store=store,
                toggles=MarkReadToggleStore(pool),
                tracked=self._tracked,
                website_key=self._website_key,
                url_name=self._url_name,
                chapter_index=self._chapter_index,
                chapter_text=self._chapter_text,
                chapter_display=self._chapter_display,
                existing=current,
            )
            result = _ack_view(title=title, description=description)
        self.stop()
        await interaction.response.edit_message(view=result)

    async def _discard(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.edit_message(
            view=_ack_view(
                title="Mark Read discarded",
                description="No changes were made to your reading progress.",
                level="warning",
            )
        )


async def _resolve_last_read_chapter_name(
    *,
    client: object,
    tracked: TrackedSeries | None,
    website_key: str,
    url_name: str,
    chapter_index: int | None,
) -> str | None:
    if chapter_index is None:
        return None
    chapters = await _resolve_chapter_list(
        client=client, tracked=tracked, website_key=website_key, url_name=url_name
    )
    _, chapter = _locate_chapter(chapters, chapter_index)
    return chapter.name if chapter is not None else None


class MarkReadButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=MARK_READ_TEMPLATE,
):
    def __init__(self, website_key: str, url_name: str, chapter_index: int) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["mark_read"][0],
                emoji=UPDATE_BUTTON_LABELS["mark_read"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:mr:{wk}:{un}:{int(chapter_index)}",
            )
        )
        self.website_key = wk
        self.url_name = un
        self.chapter_index = int(chapter_index)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> MarkReadButton:
        return cls(match["wk"], match["un"], int(match["idx"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        store = BookmarkStore(pool)
        toggles = MarkReadToggleStore(pool)
        tracked = await TrackedStore(pool).find(self.website_key, self.url_name)
        link = _series_link(tracked, self.url_name)
        existing = await store.get_bookmark(interaction.user.id, self.website_key, self.url_name)
        chapter_index = self.chapter_index
        toggle_state = await toggles.get(
            interaction.user.id, self.website_key, self.url_name, chapter_index
        )
        if toggle_state is not None:
            if toggle_state.previous_bookmark_exists:
                await store.upsert_bookmark(
                    user_id=interaction.user.id,
                    website_key=self.website_key,
                    url_name=self.url_name,
                    folder=toggle_state.previous_folder or "Reading",
                    last_read_chapter=toggle_state.previous_last_read_chapter,
                    last_read_index=toggle_state.previous_last_read_index,
                )
                if toggle_state.previous_last_read_index is not None:
                    _, restored = await _resolve_mark_read_chapter(
                        client=interaction.client,
                        tracked=tracked,
                        website_key=self.website_key,
                        url_name=self.url_name,
                        chapter_index=toggle_state.previous_last_read_index,
                    )
                else:
                    restored = _chapter_markdown(
                        toggle_state.previous_last_read_chapter or "no chapter",
                        None,
                    )
                description = f"Restored {link} to {restored}."
            else:
                await store.delete_bookmark(interaction.user.id, self.website_key, self.url_name)
                description = f"Removed the temporary bookmark for {link}."
            await toggles.clear(interaction.user.id, self.website_key, self.url_name, chapter_index)
            await _send_ack(
                interaction,
                title=f"{emojis.CHECK}  Mark read undone",
                description=description,
            )
            return

        chapters = await _resolve_chapter_list(
            client=interaction.client,
            tracked=tracked,
            website_key=self.website_key,
            url_name=self.url_name,
        )
        clicked_position, clicked_chapter = _locate_chapter(chapters, chapter_index)
        chapter_text, chapter_display = _clicked_chapter_details(
            chapter=clicked_chapter,
            tracked=tracked,
        )
        expected_position, expected_next = _expected_next_chapter(chapters, existing)
        is_expected_next = (
            clicked_position is not None
            and expected_position is not None
            and clicked_position == expected_position
        )
        if not is_expected_next:
            confirmation = MarkReadConfirmationView(
                invoker_id=interaction.user.id,
                website_key=self.website_key,
                url_name=self.url_name,
                chapter_index=chapter_index,
                chapter_text=chapter_text,
                chapter_display=chapter_display,
                expected_next=expected_next,
                bookmark_snapshot=existing,
                tracked=tracked,
            )
            message = await interaction.followup.send(
                view=confirmation,
                ephemeral=True,
                wait=True,
            )
            confirmation.bind_message(message)
            return

        title, description = await _apply_mark_read(
            interaction=interaction,
            store=store,
            toggles=toggles,
            tracked=tracked,
            website_key=self.website_key,
            url_name=self.url_name,
            chapter_index=chapter_index,
            chapter_text=chapter_text,
            chapter_display=chapter_display,
            existing=existing,
        )
        await _send_ack(interaction, title=title, description=description)


class LastReadChapterButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=LAST_READ_TEMPLATE,
):
    def __init__(self, website_key: str, url_name: str) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["open_chapter"][0],
                emoji=UPDATE_BUTTON_LABELS["open_chapter"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:lr:{wk}:{un}",
            )
        )
        self.website_key = wk
        self.url_name = un

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> LastReadChapterButton:
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        store = BookmarkStore(pool)
        tracked = await TrackedStore(pool).find(self.website_key, self.url_name)
        link = _series_link(tracked, self.url_name)
        bookmark = await store.get_bookmark(interaction.user.id, self.website_key, self.url_name)

        # When the chapter list resolves, render the current last-read chapter and
        # the next chapter to read as hyperlinks; otherwise fall back to the stored
        # name as plain text.
        current: Chapter | None = None
        nxt: Chapter | None = None
        if bookmark is not None and bookmark.last_read_index is not None:
            chapters = await _resolve_chapter_list(
                client=interaction.client,
                tracked=tracked,
                website_key=self.website_key,
                url_name=self.url_name,
            )
            position, current = _locate_chapter(chapters, bookmark.last_read_index)
            if position is not None and position + 1 < len(chapters):
                nxt = chapters[position + 1]

        if current is not None and current.url:
            if bookmark is not None and bookmark.last_read_chapter != current.name:
                await store.update_last_read(
                    interaction.user.id,
                    self.website_key,
                    self.url_name,
                    chapter_text=current.name,
                    chapter_index=bookmark.last_read_index or 0,
                )
            lines = [f"Your last read chapter for {link} is {current}."]
            if nxt is not None:
                lines.append(f"**Next chapter to read:** {nxt}")
            else:
                lines.append("You're all caught up — no newer chapter to read yet.")
            await _send_ack(
                interaction, title="📖  Last read chapter", description="\n".join(lines)
            )
            return

        chapter_name = bookmark.last_read_chapter if bookmark is not None else None
        if not chapter_name and bookmark is not None:
            chapter_name = await _resolve_last_read_chapter_name(
                client=interaction.client,
                tracked=tracked,
                website_key=self.website_key,
                url_name=self.url_name,
                chapter_index=bookmark.last_read_index,
            )
            if chapter_name:
                await store.update_last_read(
                    interaction.user.id,
                    self.website_key,
                    self.url_name,
                    chapter_text=chapter_name,
                    chapter_index=bookmark.last_read_index or 0,
                )

        if chapter_name:
            title = "📖  Last read chapter"
            description = f"Your last read chapter for {link} is **{chapter_name}**."
        else:
            title = "📖  Last read chapter unavailable"
            description = f"No last read chapter name is available for {link}."

        await _send_ack(interaction, title=title, description=description)


class BookmarkButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=BOOKMARK_TEMPLATE,
):
    def __init__(self, website_key: str, url_name: str) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["bookmark"][0],
                emoji=UPDATE_BUTTON_LABELS["bookmark"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:bm:{wk}:{un}",
            )
        )
        self.website_key = wk
        self.url_name = un

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> BookmarkButton:
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        store = BookmarkStore(pool)
        tracked = await TrackedStore(pool).find(self.website_key, self.url_name)
        link = _series_link(tracked, self.url_name)
        existing = await store.get_bookmark(interaction.user.id, self.website_key, self.url_name)
        if existing is None:
            await store.upsert_bookmark(
                user_id=interaction.user.id,
                website_key=self.website_key,
                url_name=self.url_name,
                folder="Reading",
            )
            description = f"Bookmarked {link} in *Reading*."
            title = "🔖  Bookmark added"
        else:
            description = f"You already have {link} bookmarked in *{existing.folder}*."
            title = "🔖  Already bookmarked"
        await _send_ack(interaction, title=title, description=description)


class SubscribeToggleButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=SUBSCRIBE_TEMPLATE,
):
    def __init__(self, website_key: str, url_name: str) -> None:
        wk = _assert_slug(website_key, field="website_key")
        un = _assert_slug(url_name, field="url_name")
        super().__init__(
            discord.ui.Button(
                label=UPDATE_BUTTON_LABELS["subscribe"][0],
                emoji=UPDATE_BUTTON_LABELS["subscribe"][1],
                style=discord.ButtonStyle.secondary,
                custom_id=f"mu:upd:sub:{wk}:{un}",
            )
        )
        self.website_key = wk
        self.url_name = un

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> SubscribeToggleButton:
        return cls(match["wk"], match["un"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        pool = interaction.client.db  # type: ignore[attr-defined]
        tracked_store = TrackedStore(pool)
        tracked = await tracked_store.find(self.website_key, self.url_name)
        link = _series_link(tracked, self.url_name)
        guild_rows = await tracked_store.list_guilds_tracking(self.website_key, self.url_name)
        if not guild_rows:
            await _send_ack(
                interaction,
                title="🔔  Subscription unavailable",
                description=(
                    "This series isn't tracked in any server yet. Ask a server admin "
                    "to `/track new` it before subscribing."
                ),
                level="warning",
            )
            return
        # Prefer the guild the click came from, otherwise the first tracking row.
        chosen_guild_id: int | None = None
        for row in guild_rows:
            if interaction.guild_id is not None and int(row.guild_id) == int(interaction.guild_id):
                chosen_guild_id = int(row.guild_id)
                break
        if chosen_guild_id is None:
            chosen_guild_id = int(guild_rows[0].guild_id)

        subs = SubscriptionStore(pool)
        already = await subs.is_subscribed(
            interaction.user.id,
            chosen_guild_id,
            self.website_key,
            self.url_name,
        )
        if already:
            await subs.unsubscribe(
                interaction.user.id,
                chosen_guild_id,
                self.website_key,
                self.url_name,
            )
            title = "🔔  Unsubscribed"
            description = f"Unsubscribed from {link}."
        else:
            await subs.subscribe(
                interaction.user.id,
                chosen_guild_id,
                self.website_key,
                self.url_name,
            )
            title = "🔔  Subscribed"
            description = f"Subscribed to {link}."
        await _send_ack(interaction, title=title, description=description)


# Re-exports referenced by stores when Task 6 wires the callbacks.
__all__ = [
    "ALL_UPDATE_BUTTONS",
    "BOOKMARK_TEMPLATE",
    "COMPACT_BOOKMARK_TEMPLATE",
    "COMPACT_LAST_READ_TEMPLATE",
    "COMPACT_MARK_READ_TEMPLATE",
    "COMPACT_SUBSCRIBE_TEMPLATE",
    "LAST_READ_TEMPLATE",
    "MARK_READ_TEMPLATE",
    "SUBSCRIBE_TEMPLATE",
    "UPDATE_BUTTON_KEYS",
    "UPDATE_BUTTON_LABELS",
    "BookmarkButton",
    "BookmarkStore",
    "CompactBookmarkButton",
    "CompactLastReadChapterButton",
    "CompactMarkReadButton",
    "CompactSubscribeToggleButton",
    "DmSettingsStore",
    "GuildSettingsStore",
    "LastReadChapterButton",
    "MarkReadButton",
    "SubscribeToggleButton",
    "SubscriptionStore",
    "TrackedStore",
]
