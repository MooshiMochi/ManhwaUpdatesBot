from datetime import datetime

import discord
from discord import app_commands
from discord.app_commands.checks import *  # noqa: No Import Cleanup

from src.core.errors import PremiumFeatureOnly


def has_premium(*, dm_only: bool = True):
    """
    Check if the user is a patreon.
    Args:
        dm_only: Only applies the check if the interaction is in a DM channel.

    Returns:
        A check function.
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        is_dm = interaction.guild_id is None
        if dm_only and not is_dm:  # need to check in DMs only, and it's not a DM, therefore, return True
            return True
        # Check whether the user is a patreon.
        # Return True for now, since we don't have a patreon system yet.
        has_premium_account: bool = (
                await interaction.client.db.is_patreon(interaction.user.id) or
                interaction.user.id in interaction.client.owner_ids or
                any(
                    (
                        x for x in interaction.entitlements
                        if
                        x.starts_at is not None and
                        x.starts_at > datetime.now() and
                        not x.is_expired())
                )
        )
        if not has_premium_account:
            raise PremiumFeatureOnly(
                "This command requires a premium subscription to the bot.\n"
                "Check out my patreon in `/help` for more info.\n\n"
                "**Note:** > • Make sure your Patreon account is linked to your Discord account!\n"
                "> • It may take up to 10 minutes for the bot to recognize your subscription."
            )
        return has_premium_account

    return app_commands.check(predicate)
