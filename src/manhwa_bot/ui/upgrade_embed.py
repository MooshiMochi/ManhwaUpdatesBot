"""Premium upgrade embed + view (Patreon link, Discord SKU buttons)."""

from __future__ import annotations

import discord

from ..config import PremiumConfig

# Discord caps a message component row at 5 buttons total. Keep one slot for
# the optional Discord upgrade-url link button.
_MAX_SKU_BUTTONS = 4


def build_upgrade_embed(config: PremiumConfig) -> discord.Embed:
    paths: list[str] = []
    if config.patreon.enabled and config.patreon.pledge_url:
        paths.append(f"• Become a patron on [Patreon]({config.patreon.pledge_url}).")
    if config.discord.enabled and config.discord.user_sku_ids:
        paths.append("• Subscribe with the **Premium** button below.")
    if config.discord.enabled and config.discord.upgrade_url:
        paths.append(f"• See [all subscription options]({config.discord.upgrade_url}).")
    if not paths:
        paths.append("• Contact the bot owner about manual premium grants.")

    embed = discord.Embed(
        title="Premium required",
        description=(
            "This command is reserved for premium users.\n\n"
            "Choose one of the upgrade paths below:\n" + "\n".join(paths)
        ),
        colour=discord.Colour.gold(),
    )
    return embed


def build_upgrade_view(config: PremiumConfig) -> discord.ui.View:
    view = discord.ui.View(timeout=None)

    if config.patreon.enabled and config.patreon.pledge_url:
        view.add_item(
            discord.ui.Button(
                label="Patreon",
                style=discord.ButtonStyle.link,
                url=config.patreon.pledge_url,
            )
        )

    if config.discord.enabled:
        for sku_id in config.discord.user_sku_ids[:_MAX_SKU_BUTTONS]:
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.premium,
                    sku_id=sku_id,
                )
            )
        if config.discord.upgrade_url:
            view.add_item(
                discord.ui.Button(
                    label="Subscriptions",
                    style=discord.ButtonStyle.link,
                    url=config.discord.upgrade_url,
                )
            )

    return view
