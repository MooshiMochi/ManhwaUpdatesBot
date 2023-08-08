from __future__ import annotations

import asyncio
import traceback as tb
from typing import TYPE_CHECKING

import aiohttp
import discord

from src.core.errors import URLAccessFailed
from src.core.objects import ChapterUpdate, Manga
from src.core.scanners import SCANLATORS
from src.ui.views import BookmarkChapterView
from src.utils import chunked, group_items_by

if TYPE_CHECKING:
    from src.core import MangaClient

from discord.ext import commands, tasks


class UpdateCheckCog(commands.Cog):
    def __init__(self, bot: MangaClient) -> None:
        self.bot: MangaClient = bot

    async def cog_load(self):
        self.bot.logger.info("Loaded Updates Cog...")
        self.bot.add_view(BookmarkChapterView(self.bot))

        self.check_updates_task.add_exception_type(Exception)
        self.check_updates_task.start()

    async def check_updates_by_scanlator(self, mangas: list[Manga]):
        if mangas and mangas[0].scanlator not in SCANLATORS:
            self.bot.logger.error(f"Unknown scanlator {mangas[0].scanlator}")
            return

        self.bot.logger.debug(f"Checking for updates for {mangas[0].scanlator}...")
        scanner = SCANLATORS.get(mangas[0].scanlator)

        disabled_scanlators = await self.bot.db.get_disabled_scanlators()
        if scanner.name in disabled_scanlators:
            self.bot.logger.debug(f"Scanlator {scanner.name} is disabled... Ignoring update check!")
            return

        for manga in mangas:
            try:
                update_check_result: ChapterUpdate = await scanner.check_updates(
                    self.bot, manga
                )
            except URLAccessFailed as e:
                if e.status_code >= 500:
                    self.bot.logger.error(f"{scanner.name} returned status code {e.status_code}. Update check stopped.")
                    return  # cancel update check as it's unlikely to succeed.
                elif e.status_code == 404:
                    self.bot.logger.warning(f"{manga.scanlator} returned 404 for {manga.human_name}")
                elif e.status_code == 429:
                    continue  # Rate limiter should be able to handle this.
                elif e.status_code == 403:
                    self.bot.logger.warning(f"{manga.scanlator} returned 403 for {manga.human_name}")
                    return  # cancel update check as it's unlikely to succeed.
                else:
                    await self.bot.log_to_discord(
                        f"Accessing {e.manga_url} failed with status code {e.status_code or 'unknown'}"
                        " while checking for updates."
                        + (f"\nError: {e.arg_error_msg}" if e.arg_error_msg else "")
                    )
                continue
            except aiohttp.ClientHttpProxyError as e:
                if e.status >= 500:
                    pass  # proxy server error, ignore
                else:
                    self.bot.logger.error(
                        f"Error while checking for updates for {manga.human_name} ({manga.id})",
                        exc_info=e,
                    )
                    traceback = "".join(
                        tb.format_exception(type(e), e, e.__traceback__)
                    )
                    await self.bot.log_to_discord(f"Error when checking updates: {traceback}")
                continue

            except aiohttp.ClientConnectorError as e:
                curr_index = mangas.index(manga)
                await self.check_updates_by_scanlator(mangas[curr_index:])
                return  # try again from the current manga and end the current iteration.

            except Exception as e:
                self.bot.logger.error(
                    f"Error while checking for updates for {manga.human_name} ({manga.id})",
                    exc_info=e,
                )
                traceback = "".join(
                    tb.format_exception(type(e), e, e.__traceback__)
                )
                await self.bot.log_to_discord(f"Error when checking updates: {traceback}")
                continue

            if not update_check_result:
                self.bot.logger.warning(f"{manga.scanlator} returned no result for {manga.human_name}")
                continue

            elif not update_check_result.new_chapters and manga.cover_url == update_check_result.new_cover_url:
                continue

            guild_ids = await self.bot.db.get_manga_guild_ids(manga.id)
            guild_configs = await self.bot.db.get_many_guild_config(guild_ids)

            if update_check_result.new_chapters:
                for i, chapter in enumerate(update_check_result.new_chapters):
                    self.bot.logger.info(
                        f"({manga.scanlator}) {manga.human_name} ====> Chapter "
                        f"{chapter.name} released!"
                    )
                    manga.update(
                        chapter,
                        update_check_result.series_completed,
                        update_check_result.new_cover_url
                    )

                    if len(update_check_result.new_chapters) - i > 10:  # only alert for last 10 chapters.
                        continue
                    # else: <= 10

                    if not guild_configs:
                        continue

                    extra_kwargs = update_check_result.extra_kwargs[i] if len(
                        update_check_result.extra_kwargs
                    ) > i else {}
                    if not isinstance(extra_kwargs, dict):
                        self.bot.logger.warning(f"Extra kwargs must be a dict, ignoring extra kwargs:\n{extra_kwargs}")

                    for guild_config in guild_configs:
                        if not guild_config.webhook:
                            self.bot.logger.debug(
                                f"Webhook not found for guild {guild_config.guild_id}"
                            )
                            continue

                        try:
                            role_ping = "" if not guild_config.role else f"{guild_config.role.mention} "

                            if buffer := extra_kwargs.pop("buffer", None):
                                buffer.seek(0)

                            await guild_config.webhook.send(
                                (
                                    f"||<Manga ID: {manga.id} | Chapter Index: {chapter.index}>||\n"
                                    f"{role_ping}**{manga.human_name}** **{chapter.name}**"
                                    f" has been released!\n{chapter.url}"
                                ),
                                allowed_mentions=discord.AllowedMentions(roles=True),
                                **extra_kwargs,
                                view=BookmarkChapterView(self.bot),
                            )
                        except discord.HTTPException as e:
                            self.bot.logger.error(
                                f"Failed to send update for {manga.human_name}| {chapter.name}", exc_info=e
                            )
                await self.bot.db.update_series(manga)

            elif update_check_result.new_cover_url and update_check_result.new_cover_url != manga.cover_url:
                self.bot.logger.info(
                    f"({manga.scanlator}) {manga.human_name} ====> COVER UPDATE"
                )
                manga.update(None, None, update_check_result.new_cover_url)
                await self.bot.db.update_series(manga)

        self.bot.logger.debug(f"Finished checking for updates for {mangas[0].scanlator}...")

    @tasks.loop(hours=2.0)
    async def check_updates_task(self):
        self.bot.logger.info("Checking for updates...")
        try:
            # series_to_delete: list[Manga] = await self.bot.db.get_series_to_delete()
            # if series_to_delete:
            #     self.bot.logger.warning(
            #         "Deleting the following series: ================="
            #         + "\n".join(
            #             f'({x.scanlator}) ' + x.human_name for x in series_to_delete
            #         )
            #     )
            #     await self.bot.db.bulk_delete_series([m.id for m in series_to_delete])

            series_to_update: list[Manga] = await self.bot.db.get_series_to_update()

            if not series_to_update:
                return

            series_to_update: list[list[Manga]] = group_items_by(series_to_update, ["scanlator"])

            _coros = [
                self.check_updates_by_scanlator(mangas)
                for mangas in series_to_update
            ]
            chunked_coros = chunked(_coros, 2)
            for chunk in chunked_coros:
                await asyncio.gather(*chunk)
                await asyncio.sleep(20)
        except Exception as e:
            self.bot.logger.error("Error while checking for updates", exc_info=e)
            traceback = "".join(tb.format_exception(type(e), e, e.__traceback__))
            await self.bot.log_to_discord(f"Error when checking updates: {traceback}")
        finally:
            self.bot.logger.info("Update check finished =================")

    @check_updates_task.before_loop
    async def before_check_updates_task(self):
        await self.bot.wait_until_ready()


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_id:
        await bot.add_cog(UpdateCheckCog(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(UpdateCheckCog(bot))
