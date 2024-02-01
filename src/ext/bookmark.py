from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from src.static import RegExpressions

if TYPE_CHECKING:
    from src.core import MangaClient

import discord
from discord import app_commands
from discord.ext import commands
from src.core import checks

from datetime import datetime

from src.ui import BookmarkView
from src.enums import BookmarkFolderType, BookmarkViewType

from src.core.scanlators import scanlators
from src.core.errors import CustomError, MangaNotFoundError, BookmarkNotFoundError, ChapterNotFoundError, \
    UnsupportedScanlatorURLFormatError

from src.utils import get_manga_scanlator_class, create_bookmark_embed
from src.ui import autocompletes


class BookmarkCog(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot

    async def cog_load(self):
        self.bot.logger.info("Loaded Bookmarks Cog...")

    bookmark_group = app_commands.Group(name="bookmark", description="Bookmark a manga")

    @bookmark_group.command(name="new", description="Bookmark a new manga")
    @app_commands.describe(manga_url_or_id="The name of the bookmarked manga you want to view")
    @app_commands.describe(folder="The folder you want to view. If manga is specified, this is ignored.")
    @app_commands.rename(manga_url_or_id="manga_url")
    @app_commands.autocomplete(manga_url_or_id=autocompletes.bookmarks_new_cmd)
    @checks.has_premium(dm_only=True)
    async def bookmark_new(
            self,
            interaction: discord.Interaction,
            manga_url_or_id: str,
            folder: Optional[BookmarkFolderType] = BookmarkFolderType.Reading
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa

        if RegExpressions.url.search(manga_url_or_id):
            manga_url = manga_url_or_id
            scanlator = get_manga_scanlator_class(scanlators, url=manga_url)
            if scanlator is None:
                raise UnsupportedScanlatorURLFormatError(manga_url)
            manga = await scanlator.make_manga_object(manga_url)
        else:
            try:
                manga_id, scanlator_name = manga_url_or_id.split("|")
                scanlator = get_manga_scanlator_class(scanlators, key=scanlator_name)
                if not scanlator:
                    raise UnsupportedScanlatorURLFormatError(manga_id)
            except ValueError:
                raise MangaNotFoundError(manga_url_or_id)
            manga = await self.bot.db.get_series(manga_id, scanlator_name)

        existing_bookmark = await self.bot.db.get_user_bookmark(interaction.user.id, manga.id, manga.scanlator)
        if existing_bookmark:
            bookmark = existing_bookmark
        else:
            # no need to worry about extra requests as we have a caching system in place
            bookmark = await scanlator.make_bookmark_object(
                manga.url, interaction.user.id, interaction.guild_id or interaction.user.id
            )
            if not bookmark:  # not possible since we are using the manga object to create this
                raise MangaNotFoundError(manga_url_or_id)
            if bookmark.manga.available_chapters and len(bookmark.manga.available_chapters) > 0:
                bookmark.last_read_chapter = bookmark.manga.available_chapters[0]
            else:
                return await interaction.followup.send(
                    embed=discord.Embed(
                        title="No chapters available",
                        description="This manga has no chapters available to read.\n"
                                    "Consider tracking and subscribing to the manhwa to "
                                    "get notified when new chapters are available.",
                    ), ephemeral=True
                )

        bookmark.folder = folder
        bookmark.last_updated_ts = datetime.now().timestamp()
        await self.bot.db.upsert_bookmark(bookmark)
        em = create_bookmark_embed(self.bot, bookmark, scanlator.json_tree.properties.icon_url)
        await interaction.followup.send(
            f"Successfully bookmarked {bookmark.manga.title}", embed=em, ephemeral=True
        )
        return

    @bookmark_group.command(name="view", description="View your bookmark(s)")
    @app_commands.rename(series_id="manga")
    @app_commands.describe(series_id="The name of the bookmarked manga you want to view")
    @app_commands.describe(folder="The folder you want to view. If manga is specified, this is ignored.")
    @app_commands.autocomplete(series_id=autocompletes.user_bookmarks)
    @checks.has_premium(dm_only=True)
    async def bookmark_view(
            self,
            interaction: discord.Interaction,
            series_id: Optional[str] = None,
            folder: Optional[BookmarkFolderType] = None
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        bookmarks = await self.bot.db.get_user_bookmarks(interaction.user.id)

        if not bookmarks:
            return await interaction.followup.send(embed=discord.Embed(
                title="No Bookmarks",
                description="You have no bookmarks.",
                color=discord.Color.red(),
            ), ephemeral=True)

        # remove unsupported websites
        bookmarks = [bookmark for bookmark in bookmarks if bookmark.manga.scanlator in scanlators]

        view = BookmarkView(
            self.bot, interaction, bookmarks, BookmarkViewType.VISUAL, folder=folder or BookmarkFolderType.Reading
        )

        if series_id:
            try:
                manga_id, scanlator_name = series_id.split("|")
                scanlator = get_manga_scanlator_class(scanlators, key=scanlator_name)
                if not scanlator:
                    raise BookmarkNotFoundError(manga_id)
            except ValueError:
                raise BookmarkNotFoundError(series_id)

            user_bookmark = [x for x in bookmarks if x.manga.id == manga_id and x.manga.scanlator == scanlator_name]
            if not user_bookmark:
                raise BookmarkNotFoundError(manga_id)
            user_bookmark = user_bookmark[0]
            view = BookmarkView(self.bot, interaction, bookmarks, BookmarkViewType.VISUAL, folder=user_bookmark.folder)
            bookmark_index = next(
                (
                    i for i, x in enumerate(view.viewable_bookmarks)
                    if x.manga.id == manga_id and x.manga.scanlator == scanlator_name
                ), None
            )
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
    @app_commands.describe(folder="The folder you want to view. If manga is specified, this is ignored.")
    @app_commands.autocomplete(series_id=autocompletes.user_bookmarks)
    @app_commands.autocomplete(chapter_index=autocompletes.chapters)
    @checks.has_premium(dm_only=True)
    async def bookmark_update(
            self,
            interaction: discord.Interaction,
            series_id: str,
            chapter_index: Optional[str] = None,
            folder: Optional[BookmarkFolderType] = None
    ):
        if not chapter_index and not folder:
            raise CustomError("Please specify either a chapter or a folder to update the bookmark to.")

        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        try:
            manga_id, scanlator_name = series_id.split("|")
            scanlator = get_manga_scanlator_class(scanlators, key=scanlator_name)
            if not scanlator:
                raise BookmarkNotFoundError(manga_id)
        except ValueError:
            raise BookmarkNotFoundError(series_id)

        bookmark = await self.bot.db.get_user_bookmark(interaction.user.id, manga_id, scanlator_name)
        if not bookmark:
            raise BookmarkNotFoundError(manga_id)

        if chapter_index is not None:
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
        if folder is not None:
            bookmark.folder = folder

        user_subscribed: bool = False
        should_track: bool = False
        # no need to worry about available_chapters being empty because it's handled above
        if bookmark.last_read_chapter == bookmark.manga.available_chapters[-1] and not bookmark.manga.completed:
            # check if the user is subscribed to the manga with manga.id
            # if not, subscribe user
            is_tracked: bool = await self.bot.db.is_manga_tracked(
                bookmark.manga.id, bookmark.manga.scanlator, interaction.guild_id or interaction.user.id
            )
            if not await self.bot.db.is_user_subscribed(
                    interaction.user.id, bookmark.manga.id, bookmark.manga.scanlator
            ) and is_tracked:
                await self.bot.db.subscribe_user(
                    interaction.user.id, bookmark.guild_id, bookmark.manga.id, bookmark.manga.scanlator
                )
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
            success_em.description += f" and subscribed you to updates for {bookmark.manga.title}"
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
    @checks.has_premium(dm_only=True)
    async def bookmark_delete(self, interaction: discord.Interaction, series_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)  # noqa
        if RegExpressions.url.search(series_id):
            raise CustomError("This command does not accept URLs as input.\n"
                              "Please use the provided autocomplete options.")
        try:
            manga_id, scanlator_name = series_id.split("|")
            scanlator = get_manga_scanlator_class(scanlators, key=scanlator_name)
            if not scanlator:
                raise BookmarkNotFoundError(manga_id)
        except ValueError:
            raise BookmarkNotFoundError(series_id)

        deleted: bool = await self.bot.db.delete_bookmark(interaction.user.id, manga_id, scanlator_name)
        if not deleted:
            raise BookmarkNotFoundError(manga_id)
        return await interaction.followup.send("Successfully deleted bookmark", ephemeral=True)


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_ids:
        await bot.add_cog(BookmarkCog(bot), guilds=[discord.Object(id=x) for x in bot.test_guild_ids])
    else:
        await bot.add_cog(BookmarkCog(bot))
