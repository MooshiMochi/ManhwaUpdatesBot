"""Updates cog — push-driven new-chapter dispatcher.

Replaces v1's 25-minute polling cycle. The crawler emits ``notification_event``
push messages over the WebSocket; this cog fans each event out to every
guild's notifications channel and to every DM-subscribed user, then lets the
notification consumer ack the offset.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from time import monotonic
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from ..crawler.chapter import Chapter
from ..crawler.notifications import NotificationConsumer
from ..db.consumer_state import ConsumerStateStore
from ..db.dm_settings import DmSettingsStore
from ..db.guild_settings import GuildSettingsStore
from ..db.notification_actions import NotificationActionContextStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore
from ..notification_cover_relay import CoverAttachmentAsset, NotificationCoverRelay
from ..ui.components.notifications import (
    ALL_UPDATE_BUTTONS,
    build_chapter_update_view,
    build_status_change_view,
)
from ..ui.components.nsfw import should_spoiler

if TYPE_CHECKING:
    from ..bot import ManhwaBot

_log = logging.getLogger(__name__)


def _channel_is_nsfw(channel: Any) -> bool:
    """True if a Discord channel is age-gated NSFW (DMs/threads default to False)."""
    flag = getattr(channel, "is_nsfw", None)
    try:
        return bool(flag()) if callable(flag) else bool(flag)
    except Exception:
        return False


async def _resolve_messageable_channel(
    bot: commands.Bot, channel_id: int
) -> discord.abc.Messageable | None:
    """Resolve a configured channel from cache, then Discord's HTTP API."""
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.Forbidden, discord.NotFound, discord.HTTPException:
            return None
    return channel if isinstance(channel, discord.abc.Messageable) else None


class UpdatesCog(commands.Cog, name="Updates"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot: ManhwaBot = bot  # type: ignore[assignment]
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]
        self._subs = SubscriptionStore(bot.db)  # type: ignore[attr-defined]
        self._guild_settings = GuildSettingsStore(bot.db)  # type: ignore[attr-defined]
        self._dm_settings = DmSettingsStore(bot.db)  # type: ignore[attr-defined]
        self._consumer_state = ConsumerStateStore(bot.db)  # type: ignore[attr-defined]
        self._notification_actions = NotificationActionContextStore(bot.db)  # type: ignore[attr-defined]
        cfg = self.bot.config.notifications
        self._channel_sem = asyncio.Semaphore(max(1, int(cfg.fanout_concurrency)))
        self._dm_sem = asyncio.Semaphore(max(1, int(cfg.dm_fanout_concurrency)))
        self._cover_relay = NotificationCoverRelay(cfg)
        self._consumer: NotificationConsumer | None = None

    async def _scanlator_name(self, website_key: str) -> str:
        fallback = website_key.replace("_", " ").replace("-", " ").title()
        cache = getattr(self.bot, "websites_cache", None)
        crawler = getattr(self.bot, "crawler", None)
        if cache is None or crawler is None:
            return fallback
        try:
            ttl = self.bot.config.supported_websites_cache.ttl_seconds

            async def _loader() -> list[dict]:
                data = await crawler.request("supported_websites")
                return list(data.get("websites") or [])

            websites = await cache.get_or_set("websites_full", _loader, ttl)
        except Exception:
            _log.debug("scanlator display-name lookup failed", exc_info=True)
            return fallback
        for website in websites:
            if str(website.get("key") or "").strip() == website_key:
                return str(website.get("name") or fallback).strip() or fallback
        return fallback

    async def cog_load(self) -> None:
        self._consumer = NotificationConsumer(
            client=self.bot.crawler,
            store=self._consumer_state,
            consumer_key=self.bot.config.crawler.consumer_key,
            dispatch=self.dispatch,
        )
        await self._consumer.start()
        _log.info("UpdatesCog loaded; notification consumer started")

    async def cog_unload(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        await self._cover_relay.close()

    async def dispatch(self, record: dict[str, Any]) -> None:
        """Fan a single notification record out to guilds + DM subscribers."""
        started = monotonic()
        payload = record.get("payload") or {}
        website_key = str(payload.get("website_key") or "").strip()
        url_name = str(payload.get("url_name") or "").strip()
        if not website_key or not url_name:
            _log.warning(
                "notification record missing website_key/url_name: id=%s", record.get("id")
            )
            return
        if not str(payload.get("scanlator_name") or "").strip():
            payload["scanlator_name"] = await self._scanlator_name(website_key)
        if payload.get("event") == "status_change":
            recipients, attachment_sends = await self._dispatch_status_change(
                payload, website_key, url_name
            )
            self._log_dispatch_completion(
                record,
                website_key,
                recipients,
                attachment_sends,
                started,
            )
            return
        raw_chapter = payload.get("chapter") or {}
        chapter = (
            raw_chapter if isinstance(raw_chapter, Chapter) else Chapter.from_dict(raw_chapter)
        )
        # Replace the dict with a Chapter so downstream views can rely on .name/.url/etc.
        payload["chapter"] = chapter
        is_premium = chapter.is_premium

        # A premium->free transition re-notifies an already-known chapter; it is
        # not a newer release, so it must not advance the stored latest chapter.
        if not bool(payload.get("premium_freed")):
            chapter_at = (
                payload.get("released_at") or payload.get("created_at") or record.get("created_at")
            )
            try:
                await self._tracked.update_latest_chapter(
                    website_key,
                    url_name,
                    text=chapter.name or None,
                    url=chapter.url or None,
                    at=str(chapter_at) if chapter_at else None,
                )
            except Exception:
                _log.exception("failed to persist latest chapter for %s:%s", website_key, url_name)

        guild_rows = await self._tracked.list_guilds_tracking(website_key, url_name)
        user_ids = await self._subs.list_subscribers_for_series(website_key, url_name)
        series_row = (
            guild_rows[0] if guild_rows else await self._tracked.find(website_key, url_name)
        )
        if series_row is not None:
            if not str(payload.get("series_title") or "").strip():
                payload["series_title"] = series_row.title
            if not str(payload.get("series_url") or "").strip():
                payload["series_url"] = series_row.series_url
            if not str(payload.get("cover_url") or "").strip() and series_row.cover_url:
                payload["cover_url"] = series_row.cover_url
            if payload.get("is_nsfw") is None and series_row.is_nsfw is not None:
                payload["is_nsfw"] = series_row.is_nsfw

        action_context = await self._notification_actions.get_or_create(
            website_key=website_key,
            url_name=url_name,
            series_url=str(payload.get("series_url") or ""),
            chapter_index=int(chapter.index if chapter.index is not None else -1),
            chapter_name=chapter.name or None,
            chapter_url=chapter.url or None,
        )
        payload["action_token"] = action_context.token

        recipients = len(guild_rows) + len(user_ids)
        cover_asset = (
            await self._cover_relay.prepare(
                website_key=website_key,
                cover_url=payload.get("cover_url"),
            )
            if recipients
            else None
        )

        guild_tasks = [
            self._dispatch_to_guild(row, payload, is_premium, website_key, cover_asset)
            for row in guild_rows
        ]
        dm_tasks = [
            self._dispatch_to_user(uid, payload, is_premium, cover_asset) for uid in user_ids
        ]

        results = await asyncio.gather(*guild_tasks, *dm_tasks, return_exceptions=True)
        self._log_dispatch_completion(
            record,
            website_key,
            recipients,
            sum(result is True for result in results),
            started,
        )

    @staticmethod
    async def _send_with_cover(
        send: Callable[..., Any],
        *,
        view_factory: Callable[[str | None], discord.ui.LayoutView],
        send_kwargs: dict[str, Any],
        cover_asset: CoverAttachmentAsset | None,
    ) -> bool:
        if cover_asset is None:
            await send(view=view_factory(None), **send_kwargs)
            return False

        file = cover_asset.to_file()
        try:
            try:
                await send(
                    view=view_factory(file.uri),
                    file=file,
                    **send_kwargs,
                )
                return True
            except discord.Forbidden, discord.NotFound:
                raise
            except discord.HTTPException:
                _log.warning("notification attachment send rejected; retrying remote cover")
                await send(view=view_factory(None), **send_kwargs)
                return False
        finally:
            file.close()

    @staticmethod
    def _log_dispatch_completion(
        record: dict[str, Any],
        website_key: str,
        recipients: int,
        attachment_sends: int,
        started: float,
    ) -> None:
        _log.info(
            "notification_dispatch event_id=%s website=%s recipients=%s "
            "attachment_sends=%s duration_ms=%s",
            record.get("id"),
            website_key,
            recipients,
            attachment_sends,
            max(0, int((monotonic() - started) * 1000)),
        )

    async def _dispatch_status_change(
        self,
        payload: dict[str, Any],
        website_key: str,
        url_name: str,
    ) -> tuple[int, int]:
        guild_rows = await self._tracked.list_guilds_tracking(website_key, url_name)
        user_ids = await self._subs.list_subscribers_for_series(website_key, url_name)
        series_row = (
            guild_rows[0] if guild_rows else await self._tracked.find(website_key, url_name)
        )
        if series_row is not None:
            if not str(payload.get("series_title") or "").strip():
                payload["series_title"] = series_row.title
            if not str(payload.get("series_url") or "").strip():
                payload["series_url"] = series_row.series_url
            if not str(payload.get("cover_url") or "").strip() and series_row.cover_url:
                payload["cover_url"] = series_row.cover_url
            if payload.get("is_nsfw") is None and series_row.is_nsfw is not None:
                payload["is_nsfw"] = series_row.is_nsfw
            try:
                await self._tracked.upsert_series(
                    website_key,
                    url_name,
                    str(payload.get("series_url") or series_row.series_url),
                    str(payload.get("series_title") or series_row.title),
                    cover_url=payload.get("cover_url") or series_row.cover_url,
                    status=payload.get("new_status") or payload.get("status") or series_row.status,
                    is_nsfw=payload.get("is_nsfw"),
                )
            except Exception:
                _log.exception("failed to persist status for %s:%s", website_key, url_name)

        recipients = len(guild_rows) + len(user_ids)
        cover_asset = (
            await self._cover_relay.prepare(
                website_key=website_key,
                cover_url=payload.get("cover_url"),
            )
            if recipients
            else None
        )
        guild_tasks = [
            self._dispatch_status_to_guild(row, payload, website_key, cover_asset)
            for row in guild_rows
        ]
        dm_tasks = [self._dispatch_status_to_user(uid, payload, cover_asset) for uid in user_ids]
        results = await asyncio.gather(*guild_tasks, *dm_tasks, return_exceptions=True)

        if bool(payload.get("terminal")):
            try:
                await self._subs.unsubscribe_all_for_series(website_key, url_name)
                await self._tracked.delete_series(website_key, url_name)
            except Exception:
                _log.exception("terminal cleanup failed for %s:%s", website_key, url_name)
        return recipients, sum(result is True for result in results)

    async def _dispatch_status_to_guild(
        self,
        row: Any,
        payload: dict,
        website_key: str,
        cover_asset: CoverAttachmentAsset | None,
    ) -> bool:
        async with self._channel_sem:
            try:
                settings = await self._guild_settings.get(row.guild_id)
                channel_id = await self._resolve_channel_id(row.guild_id, website_key, settings)
                if channel_id is None:
                    _log.warning("guild %s has no notification channel; skipping", row.guild_id)
                    return False
                channel = await _resolve_messageable_channel(self.bot, channel_id)
                if channel is None:
                    _log.warning(
                        "channel %s for guild %s not resolvable; dropping notification",
                        channel_id,
                        row.guild_id,
                    )
                    return False
                guild = getattr(channel, "guild", None) or self.bot.get_guild(row.guild_id)
                content = self._compose_ping(guild, row, settings)
                spoiler = should_spoiler(
                    payload.get("is_nsfw") if payload.get("is_nsfw") is not None else row.is_nsfw,
                    mode=settings.nsfw_spoiler_mode if settings is not None else "always",
                    channel_is_nsfw=_channel_is_nsfw(channel),
                )
                send_kwargs: dict[str, Any] = {}
                if content:
                    send_kwargs["allowed_mentions"] = discord.AllowedMentions(
                        everyone=False,
                        users=False,
                        roles=True,
                    )
                return await self._send_with_cover(
                    channel.send,
                    view_factory=lambda cover_media_url: build_status_change_view(
                        payload,
                        bot=self.bot,
                        ping=content,
                        spoiler=spoiler,
                        cover_media_url=cover_media_url,
                    ),
                    send_kwargs=send_kwargs,
                    cover_asset=cover_asset,
                )
            except (discord.Forbidden, discord.NotFound) as exc:
                _log.warning(
                    "guild %s status send failed (%s); skipping",
                    getattr(row, "guild_id", "?"),
                    exc.__class__.__name__,
                )
            except discord.HTTPException:
                _log.exception(
                    "guild %s status send failed with HTTP error; skipping",
                    getattr(row, "guild_id", "?"),
                )
            except Exception:
                _log.exception(
                    "unexpected error dispatching status to guild %s",
                    getattr(row, "guild_id", "?"),
                )
        return False

    async def _dispatch_status_to_user(
        self,
        user_id: int,
        payload: dict,
        cover_asset: CoverAttachmentAsset | None,
    ) -> bool:
        async with self._dm_sem:
            try:
                dm_settings = await self._dm_settings.get(user_id)
                if dm_settings is not None and not dm_settings.notifications_enabled:
                    return False
                if not await self._user_has_premium(user_id):
                    return False
                user = await self.bot.fetch_user(user_id)
                spoiler = should_spoiler(
                    payload.get("is_nsfw"),
                    mode=dm_settings.nsfw_spoiler_mode if dm_settings is not None else "always",
                )
                return await self._send_with_cover(
                    user.send,
                    view_factory=lambda cover_media_url: build_status_change_view(
                        payload,
                        bot=self.bot,
                        spoiler=spoiler,
                        cover_media_url=cover_media_url,
                    ),
                    send_kwargs={},
                    cover_asset=cover_asset,
                )
            except (discord.Forbidden, discord.NotFound) as exc:
                _log.debug("status DM to user %s skipped (%s)", user_id, exc.__class__.__name__)
            except discord.HTTPException:
                _log.warning("status DM to user %s failed with HTTP error", user_id)
            except Exception:
                _log.exception("unexpected error dispatching status DM to user %s", user_id)
        return False

    async def _dispatch_to_guild(
        self,
        row: Any,
        payload: dict,
        is_premium: bool,
        website_key: str,
        cover_asset: CoverAttachmentAsset | None,
    ) -> bool:
        async with self._channel_sem:
            try:
                settings = await self._guild_settings.get(row.guild_id)

                channel_id = await self._resolve_channel_id(row.guild_id, website_key, settings)
                if channel_id is None:
                    _log.warning("guild %s has no notification channel; skipping", row.guild_id)
                    return False

                if not self._passes_paid_chapter_gate(payload, is_premium, settings):
                    return False

                channel = await _resolve_messageable_channel(self.bot, channel_id)
                if channel is None:
                    _log.warning(
                        "channel %s for guild %s not resolvable; dropping notification",
                        channel_id,
                        row.guild_id,
                    )
                    return False

                guild = getattr(channel, "guild", None) or self.bot.get_guild(row.guild_id)
                content = self._compose_ping(guild, row, settings)
                allowed = settings.update_buttons if settings is not None else ALL_UPDATE_BUTTONS
                spoiler = should_spoiler(
                    payload.get("is_nsfw") if payload.get("is_nsfw") is not None else row.is_nsfw,
                    mode=settings.nsfw_spoiler_mode if settings is not None else "always",
                    channel_is_nsfw=_channel_is_nsfw(channel),
                )
                send_kwargs: dict[str, Any] = {}
                if content:
                    send_kwargs["allowed_mentions"] = discord.AllowedMentions(
                        everyone=False,
                        users=False,
                        roles=True,
                    )
                return await self._send_with_cover(
                    channel.send,
                    view_factory=lambda cover_media_url: build_chapter_update_view(
                        payload,
                        bot=self.bot,
                        allowed_buttons=allowed,
                        ping=content,
                        spoiler=spoiler,
                        cover_media_url=cover_media_url,
                    ),
                    send_kwargs=send_kwargs,
                    cover_asset=cover_asset,
                )
            except (discord.Forbidden, discord.NotFound) as exc:
                _log.warning(
                    "guild %s send failed (%s); skipping",
                    getattr(row, "guild_id", "?"),
                    exc.__class__.__name__,
                )
            except discord.HTTPException:
                _log.exception(
                    "guild %s send failed with HTTP error; skipping",
                    getattr(row, "guild_id", "?"),
                )
            except Exception:
                _log.exception(
                    "unexpected error dispatching to guild %s",
                    getattr(row, "guild_id", "?"),
                )
        return False

    async def _resolve_channel_id(
        self,
        guild_id: int,
        website_key: str,
        settings: Any,
    ) -> int | None:
        scanlator_rows = await self._guild_settings.list_scanlator_channels(guild_id)
        for entry in scanlator_rows:
            if str(entry.get("website_key")) == website_key:
                channel_id = entry.get("channel_id")
                if channel_id is not None:
                    return int(channel_id)
        if settings is not None and settings.notifications_channel_id is not None:
            return int(settings.notifications_channel_id)
        return None

    def _passes_paid_chapter_gate(
        self,
        payload: dict[str, Any],
        is_premium: bool,
        settings: Any,
    ) -> bool:
        """Whether a chapter event should be delivered to one recipient.

        Returns True to deliver, False to suppress. Two mirror-image rules,
        both keyed on the recipient's ``paid_chapter_notifs`` preference:

        * A *premium* chapter is suppressed for recipients who opted out of paid
          chapters.
        * A *premium_freed* chapter (one that just lost premium) goes ONLY to
          those same opted-out recipients — the ones who never saw the premium
          version — so recipients tracking premium aren't double-notified.
        """
        respect_paid = self.bot.config.notifications.respect_paid_chapter_setting
        opted_out = respect_paid and settings is not None and not settings.paid_chapter_notifs
        if bool(payload.get("premium_freed")):
            return opted_out
        if is_premium and opted_out:
            return False
        return True

    async def _user_has_premium(self, user_id: int) -> bool:
        """DM notifications are a premium perk — re-check on every delivery.

        ``/subscribe`` gates on premium at subscribe time, but premium can
        lapse afterwards; this keeps DMs flowing only while the user is still
        premium. When the premium subsystem is disabled, ``is_premium`` returns
        ``True`` so behaviour is unchanged.
        """
        try:
            ok, _ = await self.bot.premium.is_premium(user_id=user_id, guild_id=None, dm_only=True)
        except Exception:
            _log.exception("premium check failed for user %s; skipping DM", user_id)
            return False
        return ok

    @staticmethod
    def _compose_ping(guild: discord.Guild | None, row: Any, settings: Any) -> str:
        """Build the role-mention prefix, verifying the roles still exist.

        A series can carry a custom ``ping_role_id`` on top of the guild's
        default ping role — both get pinged (deduplicated when they're the
        same role). Deleted roles render as "@unknown-role" in Discord, so
        each id is verified against the guild before mentioning it.
        """

        def _role_mention(role_id: Any) -> str | None:
            try:
                rid = int(role_id)
            except TypeError, ValueError:
                return None
            if rid <= 0:
                return None
            # When the guild isn't cached we can't verify; mention best-effort.
            if guild is not None and guild.get_role(rid) is None:
                return None
            return f"<@&{rid}>"

        mentions: list[str] = []
        custom = _role_mention(getattr(row, "ping_role_id", None))
        if custom is not None:
            mentions.append(custom)
        if settings is not None:
            default = _role_mention(getattr(settings, "default_ping_role_id", None))
            if default is not None and default not in mentions:
                mentions.append(default)
        return " ".join(mentions)

    async def _dispatch_to_user(
        self,
        user_id: int,
        payload: dict,
        is_premium: bool,
        cover_asset: CoverAttachmentAsset | None,
    ) -> bool:
        async with self._dm_sem:
            try:
                dm_settings = await self._dm_settings.get(user_id)
                if dm_settings is not None and not dm_settings.notifications_enabled:
                    return False
                if not await self._user_has_premium(user_id):
                    return False
                if not self._passes_paid_chapter_gate(payload, is_premium, dm_settings):
                    return False
                user = await self.bot.fetch_user(user_id)
                allowed = (
                    dm_settings.update_buttons if dm_settings is not None else ALL_UPDATE_BUTTONS
                )
                spoiler = should_spoiler(
                    payload.get("is_nsfw"),
                    mode=dm_settings.nsfw_spoiler_mode if dm_settings is not None else "always",
                )
                return await self._send_with_cover(
                    user.send,
                    view_factory=lambda cover_media_url: build_chapter_update_view(
                        payload,
                        bot=self.bot,
                        allowed_buttons=allowed,
                        spoiler=spoiler,
                        cover_media_url=cover_media_url,
                    ),
                    send_kwargs={},
                    cover_asset=cover_asset,
                )
            except (discord.Forbidden, discord.NotFound) as exc:
                _log.debug("DM to user %s skipped (%s)", user_id, exc.__class__.__name__)
            except discord.HTTPException:
                _log.warning("DM to user %s failed with HTTP error", user_id)
            except Exception:
                _log.exception("unexpected error dispatching DM to user %s", user_id)
        return False


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UpdatesCog(bot))
