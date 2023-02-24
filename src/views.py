from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.scanlationClasses import ABCScan
    from src.core.bot import MangaClient

import discord
from discord import ButtonStyle
from discord.ui import Button, View, button

from .objects import Manga
from .utils import get_manga_scanlation_class


class SubscribeView(View):
    def __init__(
        self,
        bot: MangaClient,
        *args,
        **kwargs,
    ):
        super().__init__(*args, timeout=None, **kwargs)
        self.bot: MangaClient = bot

    @button(
        label="Subscribe",
        style=ButtonStyle.blurple,
        emoji="📚",
        custom_id="search_subscribe",
    )
    async def subscribe(self, interaction: discord.Interaction, button: Button):

        message: discord.Message = interaction.message
        manga_home_url = message.embeds[0].fields[-1].value

        scanlator: ABCScan = get_manga_scanlation_class(manga_home_url)

        url_name = scanlator.get_rx_url_name(manga_home_url)
        series_url: str = manga_home_url
        series_id = scanlator.get_manga_id(series_url)

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

        completed = await scanlator.is_series_completed(self.bot, series_id, url_name)

        if completed:
            em = discord.Embed(title="Series Completed", color=discord.Color.red())
            em.description = "This series has already been completed."
            em.set_footer(text="Manga Updates", icon_url=self.bot.user.avatar.url)
            return await interaction.response.send_message(embed=em, ephemeral=True)

        latest_chapter = await scanlator.get_curr_chapter_num(
            self.bot, series_id, url_name
        )
        series_name = await scanlator.get_human_name(self.bot, series_id, url_name)

        manga: Manga = Manga(
            series_id, series_name, series_url, latest_chapter, False, scanlator.name
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
