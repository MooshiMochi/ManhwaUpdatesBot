from __future__ import annotations

import logging
from asyncio import Lock
from collections import defaultdict
from functools import partial
from typing import Optional, TYPE_CHECKING

import discord
from curl_cffi.requests import errors, Response
from discord.ext import tasks
from discord.ext.commands import Cog

from src.core.objects import ChapterUpdate, PartialManga
from src.core.scanlators import scanlators
from src.core.scanlators.classes import AbstractScanlator
from src.ui.views import BookmarkChapterView
from src.utils import check_missing_perms, group_items_by

if TYPE_CHECKING:
    from src.core import GuildSettings, MangaClient
    from src.core.objects import Chapter, Manga, MangaHeader


class UpdateCheckCog(Cog):
    def __init__(self, bot: MangaClient) -> None:
        self.bot: MangaClient = bot
        self.logger = logging.getLogger('update-check')
        self.tasks: dict[str, tuple[tasks.Loop, tasks.Loop]] = {}
        self.locks: dict[str, Lock] = {}
        self._task_iteraction_completed_count: dict[str, int] = {
            "users": 0,
            "guilds": 0
        }
        self._update_check_started: bool = False

    async def cog_load(self) -> None:
        self.logger.info('Loaded Updates Check Cog...')
        if not self._update_check_started and self.bot.is_ready():
            await self.start_update_check_tasks()
            self._update_check_started = True

    async def cog_unload(self) -> None:
        self.logger.info('Unloaded Updates Check Cog...')
        await self.stop_update_check_tasks()
        self._update_check_started = False

    async def start_update_check_tasks(self) -> None:
        self.logger.info('Starting Update Check Tasks...')
        self.logger = logging.getLogger('update-check')
        self.tasks = {}
        self.locks: dict[str, Lock] = {name: Lock() for name in scanlators.keys()}

        for name, scanlator in scanlators.items():
            update_task = tasks.loop(minutes=25, name=name)(partial(self.update_check, scanlator))
            update_task.__name__ = f"update_check_{scanlator.name}"
            # update_task.add_exception_type(Exception)
            backup_task = tasks.loop(hours=4, name=f'{name}-backup')(partial(self.backup_update_check, scanlator))
            backup_task.__name__ = f"backup_update_check_{scanlator.name}"
            # update_task.add_exception_type(Exception)
            self.tasks[name] = (update_task, backup_task)

        for task, backup_task in self.tasks.values():
            task.start()
            backup_task.start()

    async def stop_update_check_tasks(self) -> None:
        self.logger.info('Stopping Update Check Tasks...')
        for scanlator, (task, backup_task) in list(self.tasks.items()):
            task.cancel()
            backup_task.cancel()
            del self.tasks[scanlator]

    async def check_with_fp(self, scanlator: AbstractScanlator, to_check: list[MangaHeader]) -> list[ChapterUpdate]:
        """
        Check for updates using the scanlator's front page.

        Args:
            scanlator: AnstractScanlator - The scanlator to check for updates.
            to_check: list[MangaHeader] - The list of mangas to check for updates.

        Returns:
            list[ChapterUpdate] - A list of the new updates
            that need to be sent out as notifications and updated in the database.
        """
        url = getattr(scanlator.json_tree.properties, 'latest_updates_url', "Custom get_fp_partial_manga URL")
        try:
            fp_mangas: list[PartialManga] = await scanlator.get_fp_partial_manga()
        except errors.RequestsError as e:
            if e.code == 404:  # 404 means that the website URL has most likely changed
                # therefore, any later requests will also fail.
                msg = f"404 Error occurred while checking for FP updates for {scanlator.name}. URL probably changed."
                self.logger.error(msg, exc_info=e)
                await scanlator.report_error(Exception(msg), request_url=url)
                return []
            await scanlator.report_error(e, request_url=getattr(
                e.response, 'url', url
            ))
            raise e
        except Exception as e:
            await scanlator.report_error(e, request_url=url)
            raise e
        mangas_on_fp = [m for m in to_check if m in fp_mangas]
        if not mangas_on_fp:  # none of the mangas we track are on the fp ∴ they have no updates yet
            return []
        fp_mangas = [m for m in fp_mangas if m in to_check]  # Remove mangas that are not tracked\

        grouped: list[list[MangaHeader | PartialManga]] = group_items_by(  # noqa: Duplicated code will be deleted later
            [*mangas_on_fp, *fp_mangas], ["id"])
        # check and make sure that each list is of length 2.
        for i, group in enumerate(grouped):
            if len(group) != 2:
                if len(group) > 2:  # managpill has more than 1 update listed for the same manhwa
                    # group[0] = Manga
                    # group[1+] = PartialManga
                    for j in range(2, len(group)):
                        group[1].latest_chapters.extend(group[j].latest_chapters)
                    grouped[i] = group[:2]
                else:
                    self.logger.error(f"Grouped list is not of length 2: {group}")
                    await scanlator.report_error(Exception(f"Grouped list is not of length 2: {group}"))

        # Remove any groups that are not of length 2. They were reported above.
        grouped = [x for x in grouped if len(x) == 2]

        # sort the grouped manga so the Manga objects are at pos 0 and the PartialManga objects are at pos 1.
        grouped: list[tuple[MangaHeader, PartialManga]] = list(
            map(lambda x: (x[0], x[1]) if isinstance(x[1], PartialManga) else (x[1], x[0]), grouped)
        )

        chapter_updates: list[ChapterUpdate] = []
        remaining_manga: list[MangaHeader] = []

        for manga_header, partial_manga in grouped:
            if not partial_manga.latest_chapters:  # websites that don't support front page scraping return []
                remaining_manga.append(manga_header)
                continue
            manga: Manga = await self.bot.db.get_series(manga_header.id, manga_header.scanlator)
            if not manga:
                self.logger.error(f"Couldn't find manga {manga_header.id} in the database. "
                                  f"- It most likely got deleted mid update check.")
                continue
            elif manga.last_chapter is None:  # When the manga had no chapters before, and there are updates now.
                # It's best to just add all the chapters as updates.
                remaining_manga.append(manga_header)
                continue

            # unload the manga and the partial manga to account for websites that use dynamic links.
            unld_m: Manga = (await scanlator.unload_manga([manga]))[0]
            unld_pm: PartialManga = (await scanlator.unload_manga([partial_manga]))[0]

            partial_urls = {c.url for c in unld_pm.latest_chapters}

            # We will do an individual update check for the manga to make sure we didn't miss any updates.
            if unld_m.last_chapter.url not in partial_urls:
                remaining_manga.append(manga_header)
                continue

            """
            ---------
            The headache of a code block of if-statements below is based on the following logic with help from
            @Raknag77. Thank fuck for you man <3.
            ---------
            
            There are no paid chapters in the db manga.
                +- All chapters from latest locally+ in the fp are new chapters too.
            
            There are paid chapters in the db manga.
                There is a paid chapter in the fp manga.
                    First paid chapter in db is also first paid in fp.
            
                        +- All chapters from latest locally+ in the fp are new chapters too.
            
                    First paid chapter in the db is not the first paid in fp (aka next+ in fp is paid):
            
                        +- All chapters from latest locally+ in the fp are new chapters too.
                        +- All chapters from last free on the front page down up until the last free locally are updates.
                        
            
                There are no paid chapters in the fp manga. wtf is this shit???
            
                    +- All chapters from latest locally+ in the fp are new chapters too.
                    +- All locally paid chapters are now free -> update
            """

            latest_loc_in_fp_idx = next(
                i for i, c in enumerate(unld_pm.latest_chapters) if c.url == unld_m.last_chapter.url)

            # no paid chapters in the local manga
            if not unld_m.last_chapter.is_premium:  # This part of the code has been verified
                new_chapters = partial_manga.latest_chapters[latest_loc_in_fp_idx + 1:]
                for i, c in enumerate(new_chapters):
                    c.index = unld_m.last_chapter.index + i + 1
            else:  # there are paid chapters in the local manga. (last chapter is paid) == true
                first_fp_paid_ch: Chapter | None = next((c for c in unld_pm.latest_chapters if c.is_premium), None)
                first_lc_paid_ch: Chapter = next(c for c in unld_m.chapters if c.is_premium)

                # 2 possibilities:
                # 1. There is a paid chapter in the fp

                if first_fp_paid_ch is not None:
                    # There are 2 possibilities:
                    # 1. The first chapter in the fp that is paid is also the first paid chapter in the local manga.
                    if first_fp_paid_ch.url == first_lc_paid_ch.url:
                        # All chapters from fp.latest.urls.index(loc latest)+ are new updates
                        new_chapters = partial_manga.latest_chapters[latest_loc_in_fp_idx + 1:]
                        for i, c in enumerate(new_chapters):
                            c.index = unld_m.last_chapter.index + i + 1
                    else:  # The first chapter paid in the db is not the first paid chapter in the fp.
                        if first_fp_paid_ch.index > 0:  # This part of the code has been verified to work.
                            last_free_fp_ch = unld_pm.latest_chapters[first_fp_paid_ch.index - 1]
                            loc_last_free_fp_ch = next(
                                i for i, c in enumerate(unld_m.chapters) if c.url == last_free_fp_ch.url)
                            new_chapters = partial_manga.latest_chapters[latest_loc_in_fp_idx + 1:]
                            for i, c in enumerate(new_chapters):
                                c.index = unld_m.last_chapter.index + i + 1

                            for c in reversed(manga.chapters[:loc_last_free_fp_ch + 1]):
                                if c.is_premium:
                                    c.is_premium = False
                                    c.kwargs["was_premium"] = True
                                    new_chapters.insert(0, c)
                        else:
                            remaining_manga.append(manga_header)
                            continue
                else:  # There is no paid chapter in the fp, but there is a paid chapter in the local manga.
                    new_chapters = partial_manga.latest_chapters[latest_loc_in_fp_idx + 1:]
                    for i, c in enumerate(new_chapters):
                        c.index = unld_m.last_chapter.index + i + 1
                    for c in reversed(manga.chapters):
                        if c.is_premium:
                            c.is_premium = False
                            c.kwargs["was_premium"] = True
                            new_chapters.insert(0, c)

            # ---------------------------------- headache ended ----------------------------------

            chapter_updates.append(
                ChapterUpdate(manga.id, new_chapters, scanlator.name, partial_manga.cover_url, manga.status, False)
            )
            if scanlator.json_tree.properties.requires_update_embed:
                chapter_updates[-1].extra_kwargs = [
                    {"embed": scanlator.create_chapter_embed(partial_manga, chapter)}
                    for chapter in new_chapters
                ]
        individual_update_result: list[ChapterUpdate] = await self.individual_update_check(scanlator, remaining_manga)
        chapter_updates.extend(individual_update_result)

        return chapter_updates

    async def individual_update_check(self, scanlator: AbstractScanlator, to_check: list[MangaHeader]) -> list[
        ChapterUpdate]:
        """
        Check for updates individually for each manga.

        Args:
            scanlator: AnstractScanlator - The scanlator to check for updates.
            to_check: list[MangaHeader] - The list of mangas to check for updates.

        Returns:
            list[ChapterUpdate] - A list of the new updates
            that need to be sent out as notifications and updated in the database.
        """
        chapter_updates: list[ChapterUpdate] = []
        _404_in_a_row = 0
        for manga_header in to_check:
            manga: Manga = await self.bot.db.get_series(manga_header.id, manga_header.scanlator)
            if not manga:
                msg = f"Couldn't find manga {manga_header.id} in the database. - It most likely got deleted mid update check."
                self.logger.error(msg)
                await scanlator.report_error(Exception(msg))
                continue
            try:
                update = await scanlator.check_updates(manga)
                _404_in_a_row = 0
            except errors.RequestsError as e:
                resp: Response = e.response
                url = getattr(resp, 'url', manga.url)
                if e.code == 404:
                    _404_in_a_row += 1
                    msg = f"404 Error occurred while checking for updates for {scanlator.name}. Probably an invalid URL was used.\nRequested: {url}"
                    self.logger.error(msg, exc_info=e)
                    await scanlator.report_error(e, request_url=url)
                    if _404_in_a_row >= 5:
                        msg = f"5 404 Errors occurred in a row for {scanlator.name}. Skipping update check for {scanlator.name} for this cycle."
                        self.logger.error(msg, exc_info=e)
                        await scanlator.report_error(e, request_url=url)
                    continue
                elif e.code in (429, 403):
                    msg = f"{e.code} Error occurred while checking for updates for {scanlator.name}. Rate limited.\nRequested: {url}\nCancelling update check for {scanlator.name} for this cycle."
                    self.logger.error(msg, exc_info=e)
                    await scanlator.report_error(e, request_url=url)
                elif e.code >= 500:
                    msg = f"{e.code} Error occurred while checking for updates for {scanlator.name}. Website is probably down.\nRequested: {url}"
                    self.logger.error(msg, exc_info=e)
                    await scanlator.report_error(e, request_url=url)
                else:
                    msg = f"A HTTP error occurred while checking for updates for {scanlator.name}.\nRequested: {url}"
                    self.logger.error(msg, exc_info=e)
                    await scanlator.report_error(e, request_url=url)
                break
            except Exception as e:
                msg = f"An unknown error occurred while checking for updates for {scanlator.name}."
                self.logger.error(msg, exc_info=e)
                await scanlator.report_error(e, request_url=manga.url)
                break
            chapter_updates.append(update)
        return chapter_updates

    async def update_check(self, scanlator: AbstractScanlator) -> None:
        try:
            async with self.locks[scanlator.name]:
                if await self.bot.db.is_scanlator_disabled(scanlator.name):
                    self._task_iteraction_completed_count["guilds"] += 1
                    self._task_iteraction_completed_count["users"] += 1
                    self.logger.info(f'Scanlator {scanlator.name} is disabled. Skipping update check...')
                    return

                mangas_to_check: list[MangaHeader] = await self.bot.db.get_series_to_update(scanlator.name)
                if mangas_to_check:

                    self.logger.info(f'Checking for updates for {scanlator.name}...')
                    try:
                        chapter_updates: list[ChapterUpdate] = await self.check_with_fp(scanlator, mangas_to_check)
                        await self.register_new_updates_in_database(chapter_updates)
                        await self.send_update_notifications(chapter_updates)
                    except Exception as e:
                        await self._process_update_check_exception(scanlator, e)
                else:
                    self.logger.debug(f'No mangas to check for updates for {scanlator.name}.')
                self._task_iteraction_completed_count["guilds"] += 1
                self._task_iteraction_completed_count["users"] += 1
                self.logger.info(f'Finished checking for updates for {scanlator.name}...')
        except Exception as e:
            ping = list(self.bot.owner_ids)[0]
            await self.bot.log_to_discord(
                f"<@!{ping}> Critical error when checking for updates for {scanlator.name}",
                error=e
            )

    async def send_update_notifications(self, new_updates: list[ChapterUpdate]) -> None:
        """
        Send out the updates to the respective servers and users.

        Args:
            new_updates: list[ChapterUpdate] - A list of the new updates that need to be sent out as notifications and updated in the database.
        """
        guilds_to_update: dict[int, list[tuple[ChapterUpdate, int]]] = defaultdict(list)
        users_to_update: dict[discord.User, list[ChapterUpdate]] = defaultdict(list)

        # Prepare the data for updates -------------------------------------------------------
        for update in new_updates:
            guild_ids = await self.bot.db.get_manga_guild_ids(update.manga_id, update.scanlator)
            if not guild_ids:
                continue
            users = list(
                filter(
                    # The .remove(x.id) is to remove any users that are in the guild_ids list. They have their own list.
                    lambda x: x is not None and guild_ids.remove(x.id) is None,
                    [self.bot.get_user(uid) for uid in guild_ids]
                )
            )
            for user in users:
                users_to_update[user].append(update)
            for guild_id in guild_ids:
                ping_role = await self.bot.db.get_guild_manga_role_id(guild_id, update.manga_id, update.scanlator)
                guilds_to_update[guild_id].append((update, ping_role))

        # Send out the updates ----------------------------------------------------------------
        await self._send_updates_to_users(users_to_update)
        await self._send_updates_to_guilds(guilds_to_update)
        self.logger.info(f"Sent out all updates notifications.")

    async def _create_next_update_check_embed(self, guild_id: Optional[int] = None) -> discord.Embed:
        """
        Creates the embed sent at the end of every update check to show when the next update check will be.
        Returns: discord.Embed - The embed to send.
        """
        em = discord.Embed(
            title="🕑 Updates check schedule (max 25 min)",
            color=discord.Color.green()
        )
        em.set_footer(text=self.bot.user.display_name, icon_url=self.bot.user.display_avatar.url)
        desc = ""
        disabled_scanlators = await self.bot.db.get_disabled_scanlators()
        used_scanlators = await self.bot.db.get_guild_tracked_scanlators(guild_id) if guild_id else self.tasks.keys()

        # Sort the tasks alphabetically by key and filter out disabled ones.
        sorted_tasks = sorted(self.tasks.items(), key=lambda x: x[0])
        sorted_tasks = [
            (name, tasks) for name, tasks in sorted_tasks  # noqa
            if name not in disabled_scanlators and name in used_scanlators
        ]

        len_tasks = len(sorted_tasks)
        middle = (len_tasks + 1) // 2  # Left column gets the extra entry if len_tasks is odd.

        for i in range(middle):
            left_number = i + 1
            name1, (task1, _) = sorted_tasks[i]
            left_str = f"`{str(left_number).rjust(2)}. {(name1.title() + ':').ljust(15)}` <t:{int(task1.next_iteration.timestamp())}:R>"

            right_index = i + middle
            if right_index < len_tasks:
                right_number = right_index + 1
                name2, (task2, _) = sorted_tasks[right_index]
                right_str = f"`{str(right_number).rjust(2)}. {(name2.title() + ':').ljust(15)}` <t:{int(task2.next_iteration.timestamp())}:R>"
                line = f"{left_str} -- {right_str}\n"
            else:
                line = left_str + "\n"
            desc += line

        em.description = desc
        return em

    async def _send_updates_to_users(self, users: dict[discord.User, list[ChapterUpdate]]) -> None:
        """
        Send out the updates to the users.

        Args:
            users: dict[discord.User, list[ChapterUpdate]] - A dictionary of users and the updates they need to receive.
        """
        channel_notifs_sent: dict[int, int] = defaultdict(int)
        for user, updates in users.items():
            config: GuildSettings = await self.bot.db.get_guild_config(user.id)
            try:
                for update in updates:
                    manga = await self.bot.db.get_series(update.manga_id, update.scanlator)
                    for i, chapter in enumerate(update.new_chapters):
                        if chapter.is_premium:
                            # By default, if a config is not set, don't notify for premium chapters
                            if not config or config.paid_chapter_notifs is False:
                                continue
                        view = BookmarkChapterView(self.bot, chapter_link=chapter.url)
                        extra_kwargs = update.extra_kwargs[i] if update.extra_kwargs else {}
                        spoiler_text = f"||{update.manga_id}|{update.scanlator}|{chapter.index}||\n"
                        try:
                            await user.send(
                                (
                                    # f"||<Manga ID: {update.manga_id} | Chapter Index: {chapter.index}>||\n"
                                    f"**{manga.title} {chapter.name}** has been released!\n{chapter.url}\n"
                                    f"{spoiler_text}"
                                ),
                                allowed_mentions=discord.AllowedMentions(roles=True),
                                **extra_kwargs,
                                view=view,
                            )
                            channel_notifs_sent[user.id] += 1
                        except discord.HTTPException as e:
                            self.logger.error(
                                f"Failed to send update for {manga.title}| {chapter.name} to {user}", exc_info=e
                            )
                            await self.bot.log_to_discord(f"Failed to send update to user: {user.id}", error=e)
                    if update.status_changed:
                        scanlator_hyperlink = f"[{manga.scanlator.title()}]({scanlators[manga.scanlator].json_tree.properties.base_url})"
                        description = (f"The status of {manga} from {scanlator_hyperlink} has been updated to "
                                       f"**'{update.status.lower()}'**")
                        embed = discord.Embed(
                            title="Manhwa status has been upadted!", url=manga.url, description=description,
                            color=discord.Color.green()
                        )
                        try:
                            await user.send(embed=embed)
                            channel_notifs_sent[user.id] += 1
                        except discord.HTTPException as e:
                            self.logger.error(
                                f"Failed to send status update for {manga.title} to {user}", exc_info=e
                            )
                            await self.bot.log_to_discord(f"Failed to send update to user: {user.id}", error=e)
            except discord.Forbidden:
                self.logger.warning(f"Couldn't send updates to {user} - DMs are closed (Forbidden).")

        if self._task_iteraction_completed_count["users"] >= len(self.tasks) - 1:
            self._task_iteraction_completed_count["users"] = 0
            for channel in users.keys():
                # Only send updates to users that have had an update sent to them.
                if channel_notifs_sent[channel.id] > 0:
                    try:
                        await channel.send(
                            embed=await self._create_next_update_check_embed(channel.id), delete_after=25 * 60
                        )
                    except discord.HTTPException as e:
                        self.logger.error(
                            f"Failed to send the next update check embed to user {channel}", exc_info=e
                        )

    async def _send_updates_to_guilds(self, guilds: dict[int, list[tuple[ChapterUpdate, int]]]) -> None:
        """
        Send out the updates to the guilds.

        Args:
            guilds: dict[int, list[tuple[ChapterUpdate, int]]] -
            A dictionary of guilds and the updates they need to receive.
        """
        channel_notifs_sent: dict[int, int] = defaultdict(int)
        next_update_channels: set[discord.TextChannel] = set()
        for guild_id, updates in guilds.items():
            config: GuildSettings = await self.bot.db.get_guild_config(guild_id)
            # scanlator channel associations
            sca = {
                x.scanlator: x.channel for x in
                await self.bot.db.get_scanlator_channel_associations(guild_id)
            }
            if not (config and updates and config.notifications_channel):
                continue
            if not config.notifications_channel.permissions_for(config.guild.me).send_messages:
                self.logger.error(
                    f"Missing permissions to send messages in {config.notifications_channel} > {config.notifications_channel.id} for guild {config.guild}."
                )
                continue
            for update, ping_role_id in updates:
                if ping_role_id:
                    ping_role = config.guild.get_role(ping_role_id)
                else:
                    ping_role = None
                # The set in the comprehension here removes duplicates.
                ping_str = "".join([x.mention for x in {ping_role, config.default_ping_role} if x])
                title = await self.bot.db.get_series_title(update.manga_id, update.scanlator)
                number_of_chapters = len(update.new_chapters)
                for i, chapter in enumerate(update.new_chapters):
                    # Skip paid chapters if the guild doesn't want them.
                    if chapter.is_premium and not config.paid_chapter_notifs:
                        continue
                    view = None
                    spoiler_text = ""
                    extra_kwargs = update.extra_kwargs[i] if update.extra_kwargs else {}
                    if config.show_update_buttons:
                        view = BookmarkChapterView(self.bot, chapter_link=chapter.url)
                        spoiler_text = f"||{update.manga_id}|{update.scanlator}|{chapter.index}||\n"
                    channel = sca.get(update.scanlator, config.notifications_channel)
                    # 313344: send_messages, embed_links, attach_files, external_emojis
                    if check_missing_perms(channel.permissions_for(channel.guild.me), discord.Permissions(313344)):
                        self.logger.error(
                            f"Missing permissions to send messages in {channel} > {channel.id} for guild {config.guild}."
                        )
                        continue
                    try:
                        await channel.send(
                            (
                                f"**{title} {chapter.name}**"
                                f" has been released! {ping_str}\n{chapter.url}\n{spoiler_text}"
                            ),
                            allowed_mentions=discord.AllowedMentions(roles=True),
                            **extra_kwargs,
                            view=view,
                        )
                        if i == number_of_chapters - 1 and update.status_changed:
                            manga = await self.bot.db.get_series(update.manga_id, update.scanlator)
                            scanlator_hyperlink = f"[{update.scanlator.title()}]({scanlators[update.scanlator].json_tree.properties.base_url})"
                            description = (f"The status of {manga} from {scanlator_hyperlink} has been updated to "
                                           f"**'{update.status.lower()}'**")
                            embed = discord.Embed(
                                title="Manhwa status has been upadted!", url=manga.url, description=description,
                                color=discord.Color.green()
                            )
                            await channel.send(ping_str, embed=embed)
                            channel_notifs_sent[channel.id] += 1
                        channel_notifs_sent[channel.id] += 1
                    except discord.HTTPException as e:
                        self.logger.error(
                            f"Failed to send update for {title}| {chapter.name}", exc_info=e
                        )
                        await self.bot.log_to_discord(f"Failed to send update to guild: {guild_id}", error=e)
                        continue
                    next_update_channels.add(channel)

        if self._task_iteraction_completed_count["guilds"] >= len(self.tasks) - 1:
            self._task_iteraction_completed_count["guilds"] = 0
            for channel in next_update_channels:
                # only send notifs to channels that have had an update sent to them.
                if channel_notifs_sent[channel.id] > 0:
                    try:
                        await channel.send(
                            embed=await self._create_next_update_check_embed(channel.guild.id), delete_after=25 * 60
                        )
                    except discord.HTTPException as e:
                        self.logger.error(
                            f"Failed to send the next update check embed to {channel}", exc_info=e
                        )

    async def register_new_updates_in_database(self, new_updates: list[ChapterUpdate]) -> None:
        """
        Register the new updates in the database.

        Args:
            new_updates: list[ChapterUpdate] -
            A list of the new updates that need to be sent out as notifications and updated in the database.

        Returns:
            None
        """
        total_changes = 0
        for update in new_updates:
            manga = await self.bot.db.get_series(update.manga_id, update.scanlator)
            if not manga:
                continue
            for chapter in update.new_chapters:
                total_changes += 1
                manga.update(
                    chapter,
                    update.status,
                    update.new_cover_url
                )
            if manga.status != update.status:
                self.logger.info(f"Updating status of {manga.id} from {manga.status} to {update.status}")
            await self.bot.db.update_series(manga)
            if manga.completed:
                await self.bot.db.untrack_completed_series(manga.id, manga.scanlator)
                self.logger.info(f"Untracked manga {manga.id} from {manga.scanlator} as it is now completed.")
        self.bot.logger.debug(
            f"Inserted {total_changes} chapter entries for {len(new_updates)} manhwa in the database"
        )

    async def backup_update_check(self, scanlator: AbstractScanlator) -> None:
        """
        A backup update check that runs every 4hrs to make sure we don't miss any updates.
        Note: The time interval is adjustable.
        """
        try:
            async with self.locks[scanlator.name]:
                if await self.bot.db.is_scanlator_disabled(scanlator.name):
                    self.logger.info(f'Scanlator {scanlator.name} is disabled. Skipping backup update check...')
                    return

                mangas_to_check: list[MangaHeader] = await self.bot.db.get_series_to_update(scanlator.name)

                if mangas_to_check:
                    self.logger.info(f'Checking for backup updates for {scanlator.name}...')
                    try:
                        chapter_updates: list[ChapterUpdate] = await self.individual_update_check(scanlator,
                                                                                                  mangas_to_check)
                        await self.register_new_updates_in_database(chapter_updates)
                        await self.send_update_notifications(chapter_updates)
                    except Exception as e:
                        await self._process_update_check_exception(scanlator, e)
                else:
                    self.logger.debug(f'No mangas to check for backup updates for {scanlator.name}.')
                self.logger.info(f'Finished checking for backup updates for {scanlator.name}...')
        except Exception as e:
            ping = list(self.bot.owner_ids)[0]
            await self.bot.log_to_discord(
                f"<@!{ping}> Critical error when checking for backup updates for {scanlator.name}",
                error=e
            )

    async def _process_update_check_exception(self, scanlator: AbstractScanlator, e: Exception) -> None:
        skip_error = False
        # if isinstance(e, exceptions.Timeout):
        #     msg = (f"Timeout occurred while checking for updates for {scanlator.name}. "
        #            f"Website is probably down!")
        #     skip_error = True
        if isinstance(e, errors.RequestsError):
            msg = (f"HTTP Error {e.code} occurred while checking for updates for {scanlator.name}. "
                   f"Website is probably down!")
            if e.code >= 500:
                skip_error = True
            elif e.code == 404:
                msg = f"404 {e.response}."
                skip_error = True
        else:
            msg = f"Failed to check for updates for {scanlator.name}"
        await self.bot.log_to_discord(msg, error=e)
        self.logger.error(msg, exc_info=e if not skip_error else None)

    @Cog.listener()
    async def on_ready(self) -> None:
        # change the bot's status to show that updates happen every 25 minutes.
        await self.bot.change_presence(activity=discord.Game(name="Updates every 25 minutes."))
        if not self._update_check_started:
            await self.start_update_check_tasks()
            self._update_check_started = True


async def setup(bot: MangaClient) -> None:
    await bot.add_cog(UpdateCheckCog(bot))
