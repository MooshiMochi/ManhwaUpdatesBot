from __future__ import annotations

from typing import Any, TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from src.core.scanners import MangaDex
from src.static import RegExpressions
from src.ui.views import SubscribeView

if TYPE_CHECKING:
    from src.core import MangaClient


class LegacyCog(commands.Cog):
    def __init__(self, bot: MangaClient):
        self.bot = bot

    @app_commands.command(
        name="search", description="Search for a manga on Mangadex."
    )
    @app_commands.describe(query="The name of the manga.")
    async def dex_search(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if RegExpressions.mangadex_url.search(query) and (manga_id := await MangaDex.get_manga_id(query)):
            response: dict[str, Any] = await self.bot.mangadex_api.get_manga(manga_id)
        else:
            response: dict[str, Any] = await self.bot.mangadex_api.search(
                query, limit=1
            )
        results: list[dict[str, Any]] = (
            response["data"]
            if isinstance(response["data"], list)
            else [response["data"]]
        )

        if not results:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="No Results Found",
                    description="No results were found for your query.",
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

        result = results[0]

        chapters = await self.bot.mangadex_api.get_chapters_list(result["id"])
        if chapters:
            latest_chapter = chapters[-1]["attributes"]["chapter"]
        else:
            latest_chapter = "N/A"

        em = discord.Embed(
            title=f"Title: {result['attributes']['title']['en']}",
            color=discord.Color.green(),
        )
        cover_id = [
            x["id"] for x in result["relationships"] if x["type"] == "cover_art"
        ][0]
        cover_url = await self.bot.mangadex_api.get_cover(result["id"], cover_id)
        synopsis = result["attributes"]["description"].get("en")
        if not synopsis:
            # If the synopsis is not available in English, use the first available language.
            synopsis = result["attributes"]["description"].values()[0]

        em.set_image(url=cover_url)
        em.set_footer(text="Manhwa Updates", icon_url=self.bot.user.display_avatar.url)

        em.description = (
            f"**Year:** {result['attributes']['year']}\n"
            f"**Status:** {result['attributes']['status'].title()}\n"
            f"**Latest English Chapter:** {latest_chapter}\n"
        )

        em.add_field(
            name="Tags:",
            value=f"`#{'` `#'.join([x['attributes']['name']['en'] for x in result['attributes']['tags'] if x['type'] == 'tag'])}`",
        )

        max_field_length = 1024
        paragraphs = synopsis.split("\n\n")
        for paragraph in paragraphs:
            if len(paragraph) <= max_field_length:
                em.add_field(name="\u200b", value=paragraph, inline=False)
            else:
                current_field = ""
                sentences = paragraph.split(".")
                for i in range(len(sentences)):
                    sentence = sentences[i].strip() + "."
                    if len(current_field) + len(sentence) > max_field_length:
                        em.add_field(name="\u200b", value=current_field, inline=False)
                        current_field = ""
                    current_field += sentence
                    if i == len(sentences) - 1 and current_field != "":
                        em.add_field(name="\u200b", value=current_field, inline=False)

        em.add_field(
            name="MangaDex Link:",
            value=f"https://mangadex.org/title/{result['id']}",
            inline=False,
        )

        view = SubscribeView(self.bot)

        await interaction.followup.send(
            embed=em,
            ephemeral=True,
            view=view,
        )


async def setup(bot: MangaClient) -> None:
    if bot.debug and bot.test_guild_ids:
        await bot.add_cog(LegacyCog(bot), guilds=[discord.Object(id=x) for x in bot.test_guild_ids])
    else:
        await bot.add_cog(LegacyCog(bot))
