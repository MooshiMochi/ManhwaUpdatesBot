from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.bot import MangaClient

from src.core.scanners import SCANLATORS, ABCScan

import discord
from discord import ButtonStyle
from discord.ui import View, button

from src.core.objects import Manga
from src.utils import get_manga_scanlation_class


class SubscribeView(View):
    def __init__(
        self,
        bot: MangaClient,
    ):
        super().__init__(timeout=None)
        self.bot: MangaClient = bot

    @button(
        label="Subscribe",
        style=ButtonStyle.blurple,
        emoji="📚",
        custom_id="search_subscribe",
    )
    async def subscribe(self, interaction: discord.Interaction, _):

        message: discord.Message = interaction.message
        manga_home_url = message.embeds[0].fields[-1].value

        scanlator: ABCScan = get_manga_scanlation_class(SCANLATORS, manga_home_url)

        manga_url: str = manga_home_url
        series_id = scanlator.get_manga_id(manga_url)

        current_user_subs: list[Manga] = await self.bot.db.get_user_subs(
            interaction.user.id
        )
        for manga in current_user_subs:
            if manga.id == series_id:
                em = discord.Embed(
                    title="Already Subscribed", color=discord.Color.red()
                )
                em.description = "You are already subscribed to this series."
                em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
                return await interaction.response.send_message(embed=em, ephemeral=True)

        completed = await scanlator.is_series_completed(self.bot, series_id, manga_url)

        if completed:
            em = discord.Embed(title="Series Completed", color=discord.Color.red())
            em.description = "This series has already been completed."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        latest_chapter_url_hash = await scanlator.get_curr_chapter_url_hash(
            self.bot, series_id, manga_url
        )
        last_chapter_text = await scanlator.get_curr_chapter_text(
            self.bot, series_id, manga_url
        )
        series_name = await scanlator.get_human_name(self.bot, series_id, manga_url)

        manga: Manga = Manga(
            series_id, series_name, manga_url, latest_chapter_url_hash, last_chapter_text, False, scanlator.name
        )

        await self.bot.db.add_series(manga)

        await self.bot.db.subscribe_user(
            interaction.user.id, interaction.guild_id, manga.id
        )

        embed = discord.Embed(
            title="Subscribed to Series",
            color=discord.Color.green(),
            description=f"Successfully subscribed to **{series_name}!**",
        )
        embed.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)

        await interaction.response.send_message(embed=embed, ephemeral=True)
