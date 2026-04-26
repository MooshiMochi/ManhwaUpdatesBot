"""Updates cog — push-driven new-chapter dispatcher.

Replaces v1's 25-minute polling cycle. The crawler emits ``notification_event``
push messages over the WebSocket; this cog fans each event out to every
guild's notifications channel and to every DM-subscribed user, then lets the
notification consumer ack the offset.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

from .. import formatting
from ..crawler.notifications import NotificationConsumer
from ..db.consumer_state import ConsumerStateStore
from ..db.dm_settings import DmSettingsStore
from ..db.guild_settings import GuildSettingsStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore

if TYPE_CHECKING:
    from ..bot import ManhwaBot

_log = logging.getLogger(__name__)


class UpdatesCog(commands.Cog, name="Updates"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot: ManhwaBot = bot  # type: ignore[assignment]
        self._tracked = TrackedStore(bot.db)  # type: ignore[attr-defined]
        self._subs = SubscriptionStore(bot.db)  # type: ignore[attr-defined]
        self._guild_settings = GuildSettingsStore(bot.db)  # type: ignore[attr-defined]
        self._dm_settings = DmSettingsStore(bot.db)  # type: ignore[attr-defined]
        self._consumer_state = ConsumerStateStore(bot.db)  # type: ignore[attr-defined]
        cfg = self.bot.config.notifications
        self._channel_sem = asyncio.Semaphore(max(1, int(cfg.fanout_concurrency)))
        self._dm_sem = asyncio.Semaphore(max(1, int(cfg.dm_fanout_concurrency)))
        self._consumer: NotificationConsumer | None = None

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

    async def dispatch(self, record: dict[str, Any]) -> None:
        """Fan a single notification record out to guilds + DM subscribers."""
        payload = record.get("payload") or {}
        website_key = str(payload.get("website_key") or "").strip()
        url_name = str(payload.get("url_name") or "").strip()
        if not website_key or not url_name:
            _log.warning(
                "notification record missing website_key/url_name: id=%s", record.get("id")
            )
            return
        chapter = payload.get("chapter") or {}
        is_premium = bool(chapter.get("is_premium"))

        embed = formatting.chapter_update_embed(payload)

        guild_rows = await self._tracked.list_guilds_tracking(website_key, url_name)
        user_ids = await self._subs.list_subscribers_for_series(website_key, url_name)

        guild_tasks = [
            self._dispatch_to_guild(row, embed, is_premium, website_key) for row in guild_rows
        ]
        dm_tasks = [self._dispatch_to_user(uid, embed, is_premium) for uid in user_ids]

        await asyncio.gather(*guild_tasks, *dm_tasks, return_exceptions=True)

    async def _dispatch_to_guild(
        self,
        row: Any,
        embed: discord.Embed,
        is_premium: bool,
        website_key: str,
    ) -> None:
        async with self._channel_sem:
            try:
                settings = await self._guild_settings.get(row.guild_id)

                channel_id = await self._resolve_channel_id(row.guild_id, website_key, settings)
                if channel_id is None:
                    _log.warning("guild %s has no notification channel; skipping", row.guild_id)
                    return

                if (
                    is_premium
                    and self.bot.config.notifications.respect_paid_chapter_setting
                    and settings is not None
                    and not settings.paid_chapter_notifs
                ):
                    return

                channel = self.bot.get_channel(channel_id)
                if channel is None or not isinstance(channel, discord.abc.Messageable):
                    _log.debug(
                        "channel %s for guild %s not resolvable; skipping",
                        channel_id,
                        row.guild_id,
                    )
                    return

                content = self._compose_ping(row, settings)

                await channel.send(
                    content=content or None,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(roles=True),
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

    @staticmethod
    def _compose_ping(row: Any, settings: Any) -> str:
        if getattr(row, "ping_role_id", None):
            return f"<@&{int(row.ping_role_id)}>"
        if settings is not None and settings.default_ping_role_id:
            return f"<@&{int(settings.default_ping_role_id)}>"
        return ""

    async def _dispatch_to_user(
        self,
        user_id: int,
        embed: discord.Embed,
        is_premium: bool,
    ) -> None:
        async with self._dm_sem:
            try:
                dm_settings = await self._dm_settings.get(user_id)
                if dm_settings is not None and not dm_settings.notifications_enabled:
                    return
                if (
                    is_premium
                    and self.bot.config.notifications.respect_paid_chapter_setting
                    and dm_settings is not None
                    and not dm_settings.paid_chapter_notifs
                ):
                    return
                user = await self.bot.fetch_user(user_id)
                await user.send(embed=embed)
            except (discord.Forbidden, discord.NotFound) as exc:
                _log.debug("DM to user %s skipped (%s)", user_id, exc.__class__.__name__)
            except discord.HTTPException:
                _log.warning("DM to user %s failed with HTTP error", user_id)
            except Exception:
                _log.exception("unexpected error dispatching DM to user %s", user_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UpdatesCog(bot))
