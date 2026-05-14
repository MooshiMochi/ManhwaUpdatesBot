"""Reusable Components V2 primitives shared by every per-domain view factory."""

from __future__ import annotations

from typing import Any, Literal

import discord

from .. import emojis

# Limits we treat as "safe" upper bounds when rendering long text. Components
# V2 caps total TextDisplay content per message at 4000 chars; we keep
# individual blobs comfortably below that so a container can host several.
TEXT_MAX = 3800
SYNOPSIS_MAX = 2800
LIST_MAX = 3500

MU_FOOTER_TEXT = "Manhwa Updates"


def safe_truncate(text: str, limit: int, suffix: str = "…") -> str:
    """Truncate text to ``limit`` characters, appending ``suffix`` if cut."""
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    cut = max(0, limit - len(suffix))
    return text[:cut].rstrip() + suffix


def status_accent(status: str | None) -> discord.Colour:
    """Status string → semantic accent colour (ongoing/completed/hiatus/dropped)."""
    s = (status or "").lower()
    if "ongoing" in s or "releasing" in s:
        return discord.Colour.green()
    if "completed" in s or "finished" in s:
        return discord.Colour.blue()
    if "hiatus" in s or "paused" in s:
        return discord.Colour.orange()
    if "dropped" in s or "cancelled" in s:
        return discord.Colour.red()
    return discord.Colour.blurple()


def folder_accent(folder: str) -> discord.Colour:
    """Bookmark-folder string → accent colour."""
    f = (folder or "").lower()
    if "completed" in f:
        return discord.Colour.blue()
    if "dropped" in f:
        return discord.Colour.red()
    if "hold" in f:
        return discord.Colour.orange()
    if "plan" in f:
        return discord.Colour.greyple()
    return discord.Colour.green()


SeverityLevel = Literal["info", "warning", "error", "success"]


def severity_accent(level: SeverityLevel) -> discord.Colour:
    if level == "error":
        return discord.Colour.red()
    if level == "warning":
        return discord.Colour.gold()
    if level == "success":
        return discord.Colour.green()
    return discord.Colour.blurple()


def footer_section(
    bot: discord.Client | None,
    *,
    extra: str | None = None,
) -> discord.ui.Item:
    """Standard `Manhwa Updates` footer rendered as a compact TextDisplay."""
    del bot  # avatar intentionally omitted — Thumbnail accessory bloats the layout
    suffix = f" • {extra}" if extra else ""
    return discord.ui.TextDisplay(f"-# {MU_FOOTER_TEXT}{suffix}")


def series_header_section(
    *,
    title: str,
    series_url: str | None,
    cover_url: str | None,
    status: str | None = None,
    scanlator: str | None = None,
) -> discord.ui.Item:
    """Compact series header: title (hyperlinked) + status/scanlator line + cover thumb."""
    head = f"### [{title}]({series_url})" if series_url else f"### {title}"
    subtitle_parts: list[str] = []
    if status:
        subtitle_parts.append(f"**Status:** {status}")
    if scanlator:
        subtitle_parts.append(f"**Scanlator:** {scanlator}")
    body = head if not subtitle_parts else f"{head}\n{' • '.join(subtitle_parts)}"

    if cover_url:
        return discord.ui.Section(
            discord.ui.TextDisplay(body),
            accessory=discord.ui.Thumbnail(media=cover_url),
        )
    return discord.ui.TextDisplay(body)


def chapter_label(chapter: object, fallback_idx: int | None = None) -> str:
    if not isinstance(chapter, dict):
        return str(chapter)
    fallback = "?" if fallback_idx is None else f"#{fallback_idx}"
    return str(
        chapter.get("chapter")
        or chapter.get("name")
        or chapter.get("text")
        or chapter.get("chapter_number")
        or fallback
    )


def chapter_url(chapter: object) -> str:
    if not isinstance(chapter, dict):
        return ""
    return str(chapter.get("url") or chapter.get("chapter_url") or "")


def chapter_is_premium(chapter: object) -> bool:
    if not isinstance(chapter, dict):
        return False
    return bool(
        chapter.get("is_premium")
        or chapter.get("premium")
        or chapter.get("is_paid")
        or chapter.get("paid")
        or chapter.get("is_locked")
        or chapter.get("locked")
    )


def chapter_markdown(chapter: object, fallback_idx: int | None = None) -> str:
    label = chapter_label(chapter, fallback_idx)
    if chapter_is_premium(chapter):
        label = f"{emojis.LOCK} {label}"
    url = chapter_url(chapter)
    return f"[{label}]({url})" if url else label


def hero_cover_gallery(
    cover_url: str | None,
    *,
    description: str | None = None,
    spoiler: bool = False,
) -> discord.ui.MediaGallery | None:
    """Single-item MediaGallery for image-forward hero layouts. Returns None if no URL."""
    if not cover_url:
        return None
    gallery = discord.ui.MediaGallery()
    gallery.add_item(media=cover_url, description=description, spoiler=spoiler)
    return gallery


def small_separator() -> discord.ui.Separator:
    return discord.ui.Separator(spacing=discord.SeparatorSpacing.small)


def large_separator() -> discord.ui.Separator:
    return discord.ui.Separator(spacing=discord.SeparatorSpacing.large)


class BaseLayoutView(discord.ui.LayoutView):
    """Base LayoutView with invoker-lock, timeout, and disable-on-timeout."""

    def __init__(
        self,
        *,
        invoker_id: int | None = None,
        timeout: float | None = 3 * 3600,
        lock: bool = True,
    ) -> None:
        super().__init__(timeout=timeout)
        self._invoker_id = invoker_id if lock else None
        self._lock = lock
        # The bound discord.Message (if known) so on_timeout can disable
        # children in place.
        self._message: discord.Message | discord.WebhookMessage | None = None

    def bind_message(self, message: discord.Message | discord.WebhookMessage | None) -> None:
        self._message = message

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not self._lock or self._invoker_id is None:
            return True
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(
                f"{emojis.LOCK} Only the person who ran this command can use these controls.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        # Disable every interactive child we can find.
        for child in self.walk_children():
            if hasattr(child, "disabled"):
                try:
                    child.disabled = True  # type: ignore[attr-defined]
                except Exception:
                    pass
        msg = self._message
        if msg is not None:
            try:
                await msg.edit(view=self)
            except discord.HTTPException, AttributeError:
                pass


async def replace_with_layout(
    interaction: discord.Interaction,
    view: discord.ui.LayoutView,
    *,
    ephemeral: bool = False,
) -> discord.Message | discord.WebhookMessage | None:
    """Edit the original response so it switches from legacy embed/content to V2.

    Clears `content`, `embed(s)`, and `attachments` since V2 messages cannot
    coexist with those fields. Falls back to `followup.send` when the
    interaction has not been responded to yet.
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.edit_message(
                content=None,
                embed=None,
                embeds=[],
                attachments=[],
                view=view,
            )
            try:
                return await interaction.original_response()
            except discord.HTTPException:
                return None
        msg = await interaction.edit_original_response(
            content=None,
            embed=None,
            embeds=[],
            attachments=[],
            view=view,
        )
        return msg
    except discord.HTTPException:
        return await interaction.followup.send(view=view, ephemeral=ephemeral, wait=True)


def add_children(view: discord.ui.LayoutView, *items: Any) -> discord.ui.LayoutView:
    """Convenience: add multiple top-level children to a LayoutView, skipping ``None``."""
    for item in items:
        if item is None:
            continue
        view.add_item(item)
    return view
