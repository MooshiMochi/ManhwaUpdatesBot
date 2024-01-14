from __future__ import annotations

import asyncio
import logging
import traceback as tb
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

import aiohttp
import curl_cffi.requests
import discord
from aiohttp.client_exceptions import ClientConnectorError, ClientHttpProxyError

from src.core.errors import CustomError, URLAccessFailed
from src.core.objects import ChapterUpdate, Manga, PartialManga
from src.core.scanlators import scanlators
from src.core.scanlators.classes import AbstractScanlator
from src.ui.views import BookmarkChapterView
from src.utils import chunked, group_items_by

if TYPE_CHECKING:
    from src.core import MangaClient

from discord.ext import commands, tasks


class UpdateCheckCog(commands.Cog):
    def __init__(self, bot: MangaClient) -> None:
        self.bot: MangaClient = bot
        self.logger = logging.getLogger("update-check")

    async def cog_load(self):
        self.bot.logger.info("Loaded Updates Cog...")
        self.bot.add_view(BookmarkChapterView(self.bot))

        self.check_updates_task.add_exception_type(Exception, aiohttp.ClientConnectorError)
        self.check_manhwa_status.add_exception_type(Exception, aiohttp.ClientConnectorError)
        self.check_updates_task.start()
        self.check_manhwa_status.start()

    async def handle_exception(self, coro: callable, scanlator: AbstractScanlator, req_url: str) -> str:
        """
        Handles exceptions that occur while checking for updates.

        Parameters:
            coro: The coroutine that was called.
            scanlator: The scanner that was used to check for updates.
            req_url: The URL that was requested.

        Returns:
            str: a string that you can call "eval" on to get the result of the exception handling.
        """
        try:
            return await coro
        # Even though ClientConnectorError inherits from Exception, it's not getting caught.
        except (Exception, ClientConnectorError) as error:
            rv = "None"
            if isinstance(error, (ClientConnectorError, ClientHttpProxyError)):
                self.logger.warning(
                    f"[{scanlator.name.title()}] Failed to connect to proxy: {error}"
                )
                rv = "continue"

            if isinstance(error, curl_cffi.requests.RequestsError):
                if error.code == 28:
                    self.logger.warning(f"{scanlator.name.title()} timed out while checking for updates.")
                    rv = "return"  # cancel update check as it's unlikely to succeed.
            elif isinstance(error, URLAccessFailed):
                if error.status_code >= 500:
                    self.logger.error(
                        f"{scanlator.name} returned status code {error.status_code}. Update check stopped.")
                    rv = "return"  # cancel update check as it's unlikely to succeed.
                elif error.status_code == 404:
                    self.logger.warning(f"[{scanlator.name.title()}] returned 404 for {req_url}")
                elif error.status_code == 429:
                    self.logger.warning(f"[{scanlator.name.title()}] returned 429 for {req_url}")
                    rv = "return"  # Rate limiter should be able to handle this.
                elif error.status_code == 403:
                    self.logger.warning(f"[{scanlator.name.title()}] returned 403 for {req_url}")
                    rv = "return"  # cancel update check as it's unlikely to succeed.
                else:
                    await self.bot.log_to_discord(
                        f"Accessing {error.manga_url} failed with status code {error.status_code or 'unknown'}"
                        " while checking for updates."
                        + (f"\nError: {error.arg_error_msg}" if error.arg_error_msg else "")
                    )
                    rv = "continue"
            elif isinstance(error, aiohttp.ClientHttpProxyError):
                if error.status < 500:
                    self.logger.error(
                        f"Error while checking for updates for {scanlator.name.title()})",
                        exc_info=error,
                    )
                    traceback = "".join(
                        tb.format_exception(type(error), error, error.__traceback__)
                    )
                    await self.bot.log_to_discord(f"Error when checking updates: {traceback}")
                rv = "continue"
            else:
                self.logger.error(
                    f"Error while checking for updates for {scanlator.name.title()}",
                    exc_info=error,
                )
                traceback = "".join(
                    tb.format_exception(type(error), error, error.__traceback__)
                )
                await self.bot.log_to_discord(
                    f"Error when checking updates for {scanlator.name.title()}: {traceback}"
                )
                rv = "continue"
            return rv

    async def check_each_manga_url(self, scanlator: AbstractScanlator, mangas: list[Manga]) -> list[ChapterUpdate]:
        """
        Summary:
            Checks for updates by checking each manga's URL individually.

        Args:
            scanlator: The scanlator class for the mangas.
            mangas: List of manga to check for updates.

        Returns:
            list[ChapterUpdate]: A list of ChapterUpdate objects.
        """
        if not mangas:
            return []
        chapter_updates: list[ChapterUpdate] = []
        for manga in mangas:
            new_update = await self.handle_exception(scanlator.check_updates(manga), scanlator, manga.url)
            if isinstance(new_update, str):
                next_step = new_update
                match next_step:
                    case "continue" | "None":
                        continue
                    case "return":
                        return chapter_updates
                    case unknown_result:
                        self.logger.warning(f"[{manga.scanlator.title()}] Received '{unknown_result}' result!")
                        raise Exception(unknown_result)
            elif isinstance(new_update, ChapterUpdate):
                if (
                        not new_update and
                        new_update.new_cover_url == manga.cover_url and new_update.is_completed == manga.completed
                ):
                    continue
                else:
                    chapter_updates.append(new_update)
            else:
                raise TypeError(f"Unexpected type {type(new_update)} for new_update")
        return chapter_updates

    async def check_with_front_page_scraping(
            self, scanlator: AbstractScanlator, mangas: list[Manga]
    ) -> tuple[list[ChapterUpdate], list[Manga]]:
        """
        Summary:
            Checks for updates by scraping the front page of the scanlator's website.
            If the scanlator doesn't support front page scraping, it will return back all the manga that were passed in.
            Otherwise, it may return a combination of Manga and ChapterUpdate objects.

        Args:
            mangas: List of manga to check for updates.
            scanlator: The scanlator class for the mangas.

        Returns:
            tuple[list[ChapterUpdate], list[Manga]]:
                A tuple containing a list of ChapterUpdate objects and a list of Manga objects.
                The ChapterUpdate objects contain the new chapters that were found, and the Manga objects
                contain the manga that were not found in the front page scraping.

        Note:
            All error handling will be done in the caller function for simplicity.
            In this case, this is the check_updates_by_scanlator function.
        """
        partial_mangas: list[PartialManga] = []
        # setting a limit of 10 just in case all proxies are broken to avoid infinite loop with while loops.
        for attempt_num in range(1, 11):
            try:
                partial_mangas = await scanlator.get_fp_partial_manga()
                if not partial_mangas:
                    return [], mangas
                break
            except aiohttp.client.ClientConnectorError:
                if attempt_num == 10:
                    raise CustomError(
                        f"[{scanlator.name.title()}] Failed to connect to proxy after {attempt_num} attempts.",
                        var=attempt_num
                    )
                continue

        # assuming that partial_mangas is a list of the latest mangas, we don't need to check the other manga for
        # updates.
        mangas = [m for m in mangas if m in partial_mangas]
        partial_mangas = [m for m in partial_mangas if m in mangas]
        if not mangas:  # nothing to update
            return [], []
        grouped: list[list[Manga, PartialManga]] = group_items_by([*mangas, *partial_mangas], ["id"])
        # check and make sure that each list is of length 2.
        for group in grouped:
            if len(group) != 2:
                self.logger.error(f"Grouped list is not of length 2: {group}")
                await scanlator.report_error(Exception(f"Grouped list is not of length 2: {group}"))

        grouped = [x for x in grouped if len(x) == 2]

        # sort the grouped manga so the Manga objects are at pos 0 and the PartialManga objects are at pos 1.
        grouped: list[tuple[Manga, PartialManga]] = list(
            map(lambda x: x if isinstance(x[0], Manga) else x[::-1], grouped)
        )
        solo_mangas_to_check = []
        manga_chapter_updates = []
        for manga, partial_manga in grouped:
            if not partial_manga.latest_chapters:  # websites that don't support front page scraping return []
                solo_mangas_to_check.append(manga)
                continue
            elif manga.last_chapter.url == partial_manga.latest_chapters[-1].url:  # no updates here
                continue
            p_manga_chapter_urls = [x.url for x in partial_manga.latest_chapters]
            if manga.last_chapter.url in p_manga_chapter_urls:  # new chapters
                index = p_manga_chapter_urls.index(manga.last_chapter.url)
                latest_chapter_index = manga.last_chapter.index + 1
                new_chapters = []
                for chapter in partial_manga.latest_chapters[index + 1:]:
                    chapter.index = latest_chapter_index
                    latest_chapter_index += 1
                    new_chapters.append(chapter)
                manga_chapter_updates.append(
                    ChapterUpdate(
                        manga.id,
                        new_chapters,
                        manga.scanlator,
                        partial_manga.cover_url,
                        manga.status,
                    )
                )
                if scanlator.json_tree.properties.requires_update_embed:
                    manga_chapter_updates[-1].extra_kwargs = [
                        {"embed": scanlator.create_chapter_embed(partial_manga, chapter)}
                        for chapter in new_chapters
                    ]
            else:  # old chapter is not visible in listed chapters (mass released updates)
                solo_mangas_to_check.append(manga)

        return manga_chapter_updates, solo_mangas_to_check

    async def send_notifications(self, chapter_updates: list[ChapterUpdate]) -> None:
        """
        Summary:
            Sends notifications for the chapter updates in the servers.

        Args:
            chapter_updates: A list of ChapterUpdate objects.

        Returns:
            None
        """
        guilds_to_updates: dict[int, list[tuple[ChapterUpdate, int]]] = defaultdict(list)

        for update in chapter_updates:
            if not update.new_chapters:
                continue
            guild_ids = await self.bot.db.get_manga_guild_ids(update.manga_id, update.scanlator)
            if not guild_ids:
                continue
            for guild_id in guild_ids:
                ping_role_id = await self.bot.db.get_guild_manga_role_id(guild_id, update.manga_id, update.scanlator)
                guilds_to_updates[guild_id].append((update, ping_role_id))
        # {g_id: [upd1, upd2, upd3, ...], ...}

        for guild_id in guilds_to_updates:
            guild_config = await self.bot.db.get_guild_config(guild_id)
            updates = guilds_to_updates[guild_id]
            if not (guild_config and updates and guild_config.notifications_channel):
                continue
            if not guild_config.notifications_channel.permissions_for(guild_config.guild.me).send_messages:
                self.logger.warning(
                    f"Missing permissions to send messages in {guild_config.notifications_channel}"
                )
                continue
            for update, ping_role_id in updates:
                if ping_role_id:
                    ping_role = guild_config.guild.get_role(ping_role_id)
                else:
                    ping_role = None
                pings = list({ping_role, guild_config.default_ping_role})  # remove duplicates
                pings = [x.mention for x in pings if x]  # apparently role.mentionable doesn't mean you can't mention it
                formatted_pings = "".join(pings)
                manga_title = await self.bot.db.get_series_title(update.manga_id, update.scanlator)
                for i, chapter in enumerate(update.new_chapters):
                    if guild_config.show_update_buttons:
                        view = BookmarkChapterView(self.bot, chapter_link=chapter.url)
                    else:
                        view = None
                    extra_kwargs = update.extra_kwargs[i] if update.extra_kwargs else {}
                    spoiler_text = f"||{update.manga_id}|{update.scanlator}|{chapter.index}||\n"
                    if bool(guild_config.show_update_buttons) is False:
                        spoiler_text = ""
                    try:
                        await guild_config.notifications_channel.send(
                            (
                                # f"||<Manga ID: {update.manga_id} | Chapter Index: {chapter.index}>||\n"
                                f"{spoiler_text}{formatted_pings}** {manga_title} {chapter.name}**"
                                f" has been released!\n{chapter.url}"
                            ),
                            allowed_mentions=discord.AllowedMentions(roles=True),
                            **extra_kwargs,
                            view=view,
                        )
                    except discord.HTTPException as e:
                        self.logger.error(
                            f"Failed to send update for {manga_title}| {chapter.name}", exc_info=e
                        )
            next_update_ts = int(self.check_updates_task.next_iteration.timestamp())
            await guild_config.notifications_channel.send(
                embed=(
                    discord.Embed(
                        description=f"The next update check will be <t:{next_update_ts}:R> at <t:{next_update_ts}:T>")
                ).set_footer(text=self.bot.user.display_name, icon_url=self.bot.user.display_avatar.url),
                delete_after=25 * 60  # 25 min
            )

    async def update_database_entries(self, chapter_updates: list[ChapterUpdate]) -> None:
        """
        Summary:
            Updates the database entries for the chapter updates.

        Args:
            chapter_updates: A list of ChapterUpdate objects.

        Returns:
            None
        """
        total_new_chapters = 0
        for update in chapter_updates:
            manga = await self.bot.db.get_series(update.manga_id, update.scanlator)
            if not manga:
                continue
            for chapter in update.new_chapters:
                total_new_chapters += 1
                manga.update(
                    chapter,
                    update.status,
                    update.new_cover_url
                )
            await self.bot.db.update_series(manga)
        self.bot.logger.debug(
            f"Inserted {total_new_chapters} chapter entries for {len(chapter_updates)} manhwa in the database"
        )

    async def check_updates_by_scanlator(self, mangas: list[Manga]):
        if not mangas:
            return  # nothing to update
        elif mangas[0].scanlator not in scanlators:
            self.logger.error(f"Unknown scanlator {mangas[0].scanlator}")
            return
        scanlator = scanlators.get(mangas[0].scanlator)
        self.logger.debug(f"[{scanlator.name}] Checking for updates for {mangas[0].scanlator}...")

        result = await self.handle_exception(
            self.check_with_front_page_scraping(scanlator, mangas), scanlator, scanlator.json_tree.properties.base_url
        )
        if isinstance(result, tuple):
            chapter_updates, mangas_remaining = result
        else:  # type = str
            return
        if mangas_remaining:
            self.logger.debug(
                f"[{scanlator.name}] Checking individual manhwa for updates: {mangas_remaining}")
            solo_manga_updates = await self.check_each_manga_url(scanlator, mangas_remaining)
            chapter_updates.extend(solo_manga_updates)

        if not chapter_updates:
            self.logger.debug(f"[{scanlator.name}] Finished checking for updates with no updates!")
            return
        await self.update_database_entries(chapter_updates)
        await self.send_notifications(chapter_updates)
        self.logger.debug(
            f"[{scanlator.name}] Finished checking for updates with {len(chapter_updates)} manhwa updates!")

    async def check_status_update_by_scanlator(self, mangas: list[Manga]):
        if mangas and mangas[0].scanlator not in scanlators:
            self.bot.logger.error(f"Unknown scanlator {mangas[0].scanlator}")
            return

        self.bot.logger.debug(f"Checking for status updates for {mangas[0].scanlator}...")
        scanner = scanlators.get(mangas[0].scanlator)

        disabled_scanlators = await self.bot.db.get_disabled_scanlators()
        if scanner.name in disabled_scanlators:
            self.bot.logger.debug(f"Scanlator {scanner.name} is disabled... Ignoring update check!")
            return
        current_req_url: str | None = None
        for manga in mangas:
            try:
                await asyncio.sleep(20)  # delay between each request
                current_req_url = manga.url
                update_check_result: ChapterUpdate | str = await self.handle_exception(
                    scanner.check_updates(manga), scanner, manga.url
                )
                if isinstance(update_check_result, str):
                    next_step = update_check_result
                    match next_step:
                        case "continue" | "None":
                            continue
                        case "return":
                            return
                        case unknown_result:
                            self.logger.warning(f"[{manga.scanlator.title()}] Received '{unknown_result}' result!")
                            raise Exception(unknown_result)
                if not update_check_result:
                    self.bot.logger.warning(f"[{manga.scanlator}] No result returned for {manga.title} status check!")
                    continue

                elif update_check_result.is_completed == manga.completed:
                    continue
                else:
                    self.logger.debug(
                        f"[{manga.scanlator.title()}] Updated status for {manga}: "
                        f"{manga.status} -> {update_check_result.status}"
                    )
                    manga.update(status=update_check_result.status)
                guild_ids = await self.bot.db.get_manga_guild_ids(manga.id, manga.scanlator)
                guild_configs = await self.bot.db.get_many_guild_config(guild_ids)
                await self.bot.db.update_series(manga)

                for guild_config in guild_configs:
                    if not guild_config.notifications_channel:
                        continue
                    if not guild_config.notifications_channel.permissions_for(guild_config.guild.me).send_messages:
                        self.bot.logger.warning(
                            f"Missing permissions to send messages in {guild_config.notifications_channel}"
                        )
                        continue

                    ping_role_id = await self.bot.db.get_guild_manga_role_id(
                        guild_config.guild.id, manga.id, manga.scanlator
                    )

                    if ping_role_id:
                        ping_role = guild_config.guild.get_role(ping_role_id)
                    else:
                        ping_role = None
                    pings = list({ping_role, guild_config.default_ping_role})  # remove duplicates
                    pings = [x.mention for x in pings if
                             x]  # apparently role.mentionable doesn't mean you can't mention it
                    formatted_pings = "".join(pings)
                    scanlator_hyperlink = (
                        f"[{manga.scanlator.title()}]({scanlators[manga.scanlator].json_tree.properties.base_url})"
                    )
                    await guild_config.notifications_channel.send(
                        formatted_pings,
                        embed=discord.Embed(
                            title=(f"The status of {manga} from {scanlator_hyperlink} has been updated to"
                                   f"**'{manga.status.lower()}'**"),
                            color=discord.Color.green()
                        )
                    )
                    self.logger.info(f"[{manga.scanlator}] {manga.title} has been marked as {manga.status}!")
            except Exception as e:
                self.bot.logger.debug(f"[{mangas[0].scanlator}] Checking for status updates was interrupted!")
                traceback = "".join(tb.format_exception(type(e), e, e.__traceback__))
                error_as_str = f"[{mangas[0].scanlator}]: URL - {current_req_url}\n{traceback}"
                self.logger.error(error_as_str)
                await self.bot.log_to_discord(error_as_str)
                return
        self.bot.logger.debug(f"[{mangas[0].scanlator}] Finished checking for status updates!")

    @tasks.loop(minutes=25)
    async def check_updates_task(self):
        self.logger.info("Checking for updates...")
        try:
            series_to_update: list[Manga] = await self.bot.db.get_series_to_update()
            if not series_to_update:
                return

            # filter out disabled scanlators
            disabled_scanlators = await self.bot.db.get_disabled_scanlators()
            series_to_update = [x for x in series_to_update if x.scanlator not in disabled_scanlators]
            if disabled_scanlators:
                self.logger.debug(f"Disabled scanlators: {disabled_scanlators}")

            grouped_series_to_update: list[list[Manga]] = group_items_by(series_to_update, ["scanlator"])
            grouped_series_to_update = list(sorted(grouped_series_to_update, key=lambda x: len(x)))
            _coros = [
                self.check_updates_by_scanlator(mangas)
                for mangas in grouped_series_to_update
            ]
            chunked_coros = chunked(_coros, 10)
            for chunk in chunked_coros:
                await asyncio.gather(*chunk)
                # await asyncio.sleep(20)  # no need to delay since it requests different websites
        except Exception as e:
            self.logger.error("⚠️ Update Check Stopped!\n\nError while checking for updates", exc_info=e)
            traceback = "".join(tb.format_exception(type(e), e, e.__traceback__))
            await self.bot.log_to_discord(f"Error when checking updates: {traceback}")
        finally:
            self.logger.info("Update check finished =================")
            next_update_ts = int(self.check_updates_task.next_iteration.timestamp())
            # change the bot's status to show when the next update check will be
            await self.bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"for updates at ▢▢:{datetime.fromtimestamp(next_update_ts):%M}"
                )
            )

    @tasks.loop(hours=24.0)
    async def check_manhwa_status(self):

        self.logger.info("Checking for manga status...")
        try:
            series_to_check: list[Manga] = await self.bot.db.get_series_to_update()
            if not series_to_check:
                return

            # filter out disabled scanlators
            disabled_scanlators = await self.bot.db.get_disabled_scanlators()
            series_to_check = [x for x in series_to_check if x.scanlator not in disabled_scanlators]
            if disabled_scanlators:
                self.logger.debug(f"Disabled scanlators: {disabled_scanlators}")
            grouped_series_to_check: list[list[Manga]] = group_items_by(series_to_check, ["scanlator"])
            grouped_series_to_check = list(sorted(grouped_series_to_check, key=lambda x: len(x)))
            _coros = [
                self.check_status_update_by_scanlator(mangas)
                for mangas in grouped_series_to_check
            ]
            chunked_coros = chunked(_coros, 10)  # 10 coros at a time = ~10 proxy concurrent connections
            for chunk in chunked_coros:
                await asyncio.gather(*chunk)

        except Exception as e:
            self.logger.error("⚠️ Status Update Check Stopped!\n\nError while checking for status", exc_info=e)
            traceback = "".join(tb.format_exception(type(e), e, e.__traceback__))
            await self.bot.log_to_discord(f"Error when checking manhwa status: {traceback}")
        finally:
            self.logger.info("Status check finished =================")

    @check_updates_task.before_loop
    async def before_check_updates_task(self):
        await self.bot.wait_until_ready()

    @check_manhwa_status.before_loop
    async def before_status_check_task(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(300)  # add a 5 min delay


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_ids:
        await bot.add_cog(UpdateCheckCog(bot), guilds=[discord.Object(id=x) for x in bot.test_guild_ids])
    else:
        await bot.add_cog(UpdateCheckCog(bot))
