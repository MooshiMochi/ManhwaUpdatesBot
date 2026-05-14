"""Premium upgrade prompt (Patreon link + Discord SKU buttons) as a V2 LayoutView."""

from __future__ import annotations

import discord

from ...config import PremiumConfig
from .. import emojis
from .base import BaseLayoutView, footer_section

# Discord caps a component row at 5 buttons total.
_MAX_SKU_BUTTONS = 4


def build_upgrade_view(
    config: PremiumConfig,
    *,
    bot: discord.Client | None = None,
) -> discord.ui.LayoutView:
    """Hero gold upgrade prompt with Patreon link + Discord premium SKU buttons."""
    paths: list[str] = []
    if config.patreon.enabled and config.patreon.pledge_url:
        paths.append(f"• Become a patron on [Patreon]({config.patreon.pledge_url}).")
    if config.discord.enabled and config.discord.user_sku_ids:
        paths.append("• Subscribe with the **Premium** button below.")
    if config.discord.enabled and config.discord.upgrade_url:
        paths.append(f"• See [all subscription options]({config.discord.upgrade_url}).")
    if not paths:
        paths.append("• Contact the bot owner about manual premium grants.")

    body = (
        "This command is reserved for **premium users**.\n\n"
        "Choose one of the upgrade paths below:\n" + "\n".join(paths)
    )

    container = discord.ui.Container(
        discord.ui.TextDisplay(f"## {emojis.LOCK}  Premium required"),
        discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
        discord.ui.TextDisplay(body),
        accent_colour=discord.Colour.gold(),
    )

    row = discord.ui.ActionRow()
    has_button = False
    if config.patreon.enabled and config.patreon.pledge_url:
        row.add_item(
            discord.ui.Button(
                label="Patreon",
                style=discord.ButtonStyle.link,
                url=config.patreon.pledge_url,
                emoji="🟧",
            )
        )
        has_button = True

    if config.discord.enabled:
        for sku_id in config.discord.user_sku_ids[:_MAX_SKU_BUTTONS]:
            row.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.premium,
                    sku_id=sku_id,
                )
            )
            has_button = True
        if config.discord.upgrade_url:
            row.add_item(
                discord.ui.Button(
                    label="Subscriptions",
                    style=discord.ButtonStyle.link,
                    url=config.discord.upgrade_url,
                )
            )
            has_button = True

    if has_button:
        container.add_item(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))

    if bot is not None:
        container.add_item(footer_section(bot))

    view = BaseLayoutView(invoker_id=None, lock=False, timeout=None)
    view.add_item(container)
    if has_button:
        view.add_item(row)
    return view
