from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.core import MangaClient

from src.core.scanners import SCANLATORS
from src.core.objects import ABCScan

import discord

from discord.ext import commands
from src.utils import get_manga_scanlator_class, create_bookmark_embed
from discord import app_commands
from src.core.errors import MangaNotFound, BookmarkNotFound, ChapterNotFound
from src.ui import BookmarkView
from src.enums import BookmarkViewType


class BookmarkCog(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot: MangaClient = bot

    async def cog_load(self):
        self.bot.logger.info("Loaded Bookmarks Cog...")

    async def bookmark_autocomplete(
            self: Any, interaction: discord.Interaction, argument: str
    ) -> list[discord.app_commands.Choice]:
        bookmarks = await self.bot.db.get_user_bookmarks_autocomplete(interaction.user.id, argument)
        if not bookmarks:
            return []

        return [
                   discord.app_commands.Choice(
                       name=x[1],
                       value=x[0]
                   ) for x in bookmarks
               ][:25]

    async def chapter_autocomplete(
            self: Any, interaction: discord.Interaction, argument: str
    ) -> list[discord.app_commands.Choice]:
        series_id = interaction.namespace["manga"]
        if series_id is None:
            return []
        chapters = await self.bot.db.get_series_chapters(series_id, argument)
        if not chapters:
            return []

        return [
                   discord.app_commands.Choice(
                       name=chp.name[:97] + ("..." if len(chp.name) > 100 else ''),
                       value=str(chp.index)
                   ) for chp in chapters
               ][:25]

    bookmark_group = app_commands.Group(name="bookmark", description="Bookmark a manga")

    @bookmark_group.command(name="new", description="Bookmark a new manga")
    @app_commands.describe(manga_url="The url of the manga you want to bookmark")
    async def bookmark_new(self, interaction: discord.Interaction, manga_url: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        scanner: ABCScan = get_manga_scanlator_class(SCANLATORS, manga_url)
        if not scanner:
            em = discord.Embed(title="Invalid URL", color=discord.Color.red())
            em.description = (
                "The URL you provided does not follow any of the known url formats.\n"
                "See `/supported_websites` for a list of supported websites and their url formats."
            )
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.followup.send(embed=em, ephemeral=True)

        manga_id = await scanner.get_manga_id(self.bot, manga_url)
        existing_bookmark = await self.bot.db.get_user_bookmark(interaction.user.id, manga_id)
        if existing_bookmark:
            print("Bookmark already exists")
            bookmark = existing_bookmark
        else:
            print("Bookmark does not exist")
            bookmark = await scanner.make_bookmark_object(
                self.bot, manga_id, manga_url, interaction.user.id, interaction.guild.id
            )
            if not bookmark:
                raise MangaNotFound(manga_url)
            bookmark.last_read_chapter = bookmark.manga.available_chapters[0]

        bookmark.user_created = True
        await self.bot.db.upsert_bookmark(bookmark)
        em = create_bookmark_embed(self.bot, bookmark, scanner.icon_url)
        await interaction.followup.send(
            f"Successfully bookmarked {bookmark.manga.human_name}", embed=em, ephemeral=True
        )
        return

    @bookmark_group.command(name="view", description="View your bookmark(s)")
    @app_commands.rename(series_id="manga")
    @app_commands.describe(series_id="The name of the bookmarked manga you want to view")
    @app_commands.autocomplete(series_id=bookmark_autocomplete)
    async def bookmark_view(self, interaction: discord.Interaction, series_id: Optional[str] = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        bookmarks = await self.bot.db.get_user_bookmarks(interaction.user.id)
        if not bookmarks:
            return await interaction.followup.send("You have no bookmarks", ephemeral=True)

        view = BookmarkView(self.bot, interaction, bookmarks, BookmarkViewType.VISUAL)

        if series_id:
            bookmark_index = next((i for i, x in enumerate(view.bookmarks) if x.manga.id == series_id), None)
            if bookmark_index is None:
                hidden_bookmark = await self.bot.db.get_user_bookmark(interaction.user.id, series_id)
                if hidden_bookmark:
                    em = create_bookmark_embed(self.bot, hidden_bookmark, hidden_bookmark.scanner.icon_url)
                    await interaction.response.followup.send(embed=em, ephemeral=True)
                    view.stop()
                    return

                raise BookmarkNotFound()
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
    @app_commands.autocomplete(series_id=bookmark_autocomplete)
    @app_commands.autocomplete(chapter_index=chapter_autocomplete)
    async def bookmark_update(self, interaction: discord.Interaction, series_id: str, chapter_index: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        chapters = await self.bot.db.get_series_chapters(series_id)
        if not chapters:
            raise BookmarkNotFound()

        chapter = chapters[int(chapter_index)]
        if not chapter:
            raise ChapterNotFound()
        await self.bot.db.update_last_read_chapter(interaction.user.id, series_id, chapter)
        await interaction.followup.send(f"Successfully updated bookmark to {chapter.name}", ephemeral=True)
        return

    @bookmark_group.command(name="delete", description="Delete a bookmark")
    @app_commands.rename(series_id="manga")
    @app_commands.describe(series_id="The name of the bookmarked manga you want to delete")
    @app_commands.autocomplete(series_id=bookmark_autocomplete)
    async def bookmark_delete(self, interaction: discord.Interaction, series_id: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted: bool = await self.bot.db.delete_bookmark(interaction.user.id, series_id)
        if not deleted:
            raise BookmarkNotFound()
        return await interaction.followup.send("Successfully deleted bookmark", ephemeral=True)


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_id:
        await bot.add_cog(BookmarkCog(bot), guild=discord.Object(id=bot.test_guild_id))
    else:
        await bot.add_cog(BookmarkCog(bot))
