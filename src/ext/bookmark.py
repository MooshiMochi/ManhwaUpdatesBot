from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from src.static import RegExpressions

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
from discord import app_commands
from discord.ext import commands

from datetime import datetime

from src.ui import BookmarkView
from src.enums import BookmarkViewType

from src.core.objects import ABCScan
from src.core.scanners import SCANLATORS
from src.core.errors import MangaNotFoundError, BookmarkNotFoundError, ChapterNotFoundError

from src.utils import get_manga_scanlator_class, create_bookmark_embed, respond_if_limit_reached
from src.ui import autocompletes


class BookmarkCog(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot

    async def cog_load(self):
        self.bot.logger.info("Loaded Bookmarks Cog...")

    bookmark_group = app_commands.Group(name="bookmark", description="Bookmark a manga")

    @bookmark_group.command(name="new", description="Bookmark a new manga")
    @app_commands.describe(manga_url_or_id="The name of the bookmarked manga you want to view")
    @app_commands.rename(manga_url_or_id="manga_url")
    @app_commands.autocomplete(manga_url_or_id=autocompletes.manga)
    async def bookmark_new(self, interaction: discord.Interaction, manga_url_or_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        scanner: ABCScan = get_manga_scanlator_class(SCANLATORS, manga_url_or_id)
        for scan in SCANLATORS.values():
            if scan.rx.search(manga_url_or_id):
                scanner = scan
                break
        manga_url = manga_url_or_id

        if RegExpressions.url.search(manga_url_or_id):
            if not scanner:
                em = discord.Embed(title="Invalid URL", color=discord.Color.red())
                em.description = (
                    "The URL you provided does not follow any of the known url formats.\n"
                    "See `/supported_websites` for a list of supported websites and their url formats."
                )
                em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)
                return await interaction.followup.send(embed=em, ephemeral=True)

            manga_id = await scanner.get_manga_id(manga_url_or_id)
        else:
            manga_id = manga_url_or_id
            manga_obj = await self.bot.db.get_series(manga_id)
            if not manga_obj:
                raise MangaNotFoundError(manga_url_or_id)
            scanner = get_manga_scanlator_class(SCANLATORS, key=manga_obj.scanlator)
            manga_url = manga_obj.url

        existing_bookmark = await self.bot.db.get_user_bookmark(interaction.user.id, manga_id)

        if existing_bookmark:
            bookmark = existing_bookmark
        else:

            bookmark = await respond_if_limit_reached(
                scanner.make_bookmark_object(
                    manga_id, manga_url, interaction.user.id, interaction.guild.id
                ),
                interaction
            )
            # bookmark = await scanner.make_bookmark_object(
            #     self.bot, manga_id, manga_url, interaction.user.id, interaction.guild.id
            # )
            if bookmark == "LIMIT_REACHED":
                return
            elif not bookmark:
                raise MangaNotFoundError(manga_url_or_id)
            try:
                bookmark.last_read_chapter = bookmark.manga.available_chapters[0]
            except IndexError:
                return await interaction.followup.send(
                    embed=discord.Embed(
                        title="No chapters available",
                        description="This manga has no chapters available to read.\nConsider using `/subscribe` to "
                                    "get notified when new chapters are available.",
                    ), ephemeral=True
                )

        bookmark.user_created = True
        bookmark.last_updated_ts = datetime.now().timestamp()
        await self.bot.db.upsert_bookmark(bookmark)
        em = create_bookmark_embed(self.bot, bookmark, scanner.icon_url)
        await interaction.followup.send(
            f"Successfully bookmarked {bookmark.manga.human_name}", embed=em, ephemeral=True
        )
        return

    @bookmark_group.command(name="view", description="View your bookmark(s)")
    @app_commands.rename(series_id="manga")
    @app_commands.describe(series_id="The name of the bookmarked manga you want to view")
    @app_commands.autocomplete(series_id=autocompletes.user_bookmarks)
    async def bookmark_view(self, interaction: discord.Interaction, series_id: Optional[str] = None):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        bookmarks = await self.bot.db.get_user_bookmarks(interaction.user.id)

        if not bookmarks:
            return await interaction.followup.send(embed=discord.Embed(
                title="No Bookmarks",
                description="You have no bookmarks.",
                color=discord.Color.red(),
            ), ephemeral=True)

        # remove unsupported websites
        bookmarks = [bookmark for bookmark in bookmarks if bookmark.manga.scanlator in SCANLATORS]

        view = BookmarkView(self.bot, interaction, bookmarks, BookmarkViewType.VISUAL)

        if series_id:
            bookmark_index = next((i for i, x in enumerate(view.bookmarks) if x.manga.id == series_id), None)
            if bookmark_index is None:
                hidden_bookmark = await self.bot.db.get_user_bookmark(interaction.user.id, series_id)
                if hidden_bookmark:
                    em = create_bookmark_embed(self.bot, hidden_bookmark, hidden_bookmark.scanner.icon_url)
                    await interaction.response.followup.send(embed=em, ephemeral=True)  # noqa
                    view.stop()
                    return

                raise BookmarkNotFoundError()
            view.visual_item_index = bookmark_index

        # noinspection PyProtectedMember
        em = view._get_display_embed()
        view.message = await interaction.followup.send(embed=em, view=view, ephemeral=True)
        return

    @bookmark_group.command(name="update", description="Update a bookmark")
    @app_commands.rename(series_id="manga")
    @app_commands.rename(chapter_index="chapter")
    @app_commands.describe(series_id="The name of the bookmarked manga you want to update")
    @app_commands.describe(chapter_index="The chapter you want to update the bookmark to")
    @app_commands.autocomplete(series_id=autocompletes.user_bookmarks)
    @app_commands.autocomplete(chapter_index=autocompletes.chapters)
    async def bookmark_update(self, interaction: discord.Interaction, series_id: str, chapter_index: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        bookmark = await self.bot.db.get_user_bookmark(interaction.user.id, series_id)
        if not bookmark:
            raise BookmarkNotFoundError()

        try:
            chapter_index = int(chapter_index)
        except ValueError:
            raise ChapterNotFoundError()
        try:
            new_chapter = bookmark.manga.available_chapters[chapter_index]
        except (IndexError, TypeError):
            raise ChapterNotFoundError()

        bookmark.last_read_chapter = new_chapter
        bookmark.last_updated_ts = datetime.now().timestamp()

        user_subscribed: bool = False
        should_track: bool = False
        # no need to worry about available_chapters being empty because it's handled above
        if bookmark.last_read_chapter == bookmark.manga.available_chapters[-1] and not bookmark.manga.completed:
            # check if the user is subscribed to the manga with manga.id
            # if not, subscribe user
            is_tracked: bool = await self.bot.db.is_manga_tracked(interaction.guild_id, bookmark.manga.id)
            if not await self.bot.db.is_user_subscribed(interaction.user.id, bookmark.manga.id) and is_tracked:
                await self.bot.db.subscribe_user(interaction.user.id, bookmark.guild_id, bookmark.manga.id)
                user_subscribed = True
            elif not is_tracked:
                should_track = True

        await self.bot.db.upsert_bookmark(bookmark)
        success_em = discord.Embed(
            title="Bookmark Updated",
            description=f"Successfully updated bookmark to {bookmark.last_read_chapter}",
            color=discord.Color.green(),
        )
        if user_subscribed:
            success_em.description += f" and subscribed you to updates for {bookmark.manga.human_name}"
            await interaction.followup.send(embed=success_em, ephemeral=True)
        elif should_track:
            success_em.description += "\n\n*You should consider tracking and subscribing to this manga to get updates.*"
            await interaction.followup.send(embed=success_em, ephemeral=True)
        else:
            await interaction.followup.send(embed=success_em, ephemeral=True)

    @bookmark_group.command(name="delete", description="Delete a bookmark")
    @app_commands.rename(series_id="manga")
    @app_commands.describe(series_id="The name of the bookmarked manga you want to delete")
    @app_commands.autocomplete(series_id=autocompletes.user_bookmarks)
    async def bookmark_delete(self, interaction: discord.Interaction, series_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        deleted: bool = await self.bot.db.delete_bookmark(interaction.user.id, series_id)
        if not deleted:
            raise BookmarkNotFoundError()
        return await interaction.followup.send("Successfully deleted bookmark", ephemeral=True)


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_ids:
        await bot.add_cog(BookmarkCog(bot), guilds=[discord.Object(id=x) for x in bot.test_guild_ids])
    else:
        await bot.add_cog(BookmarkCog(bot))
