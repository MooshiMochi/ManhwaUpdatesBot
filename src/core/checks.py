from datetime import datetime

import discord
from discord import app_commands
from discord.app_commands.checks import *  # noqa: No Import Cleanup

from src.core.errors import PremiumFeatureOnly
from src.utils import check_missing_perms


def has_permissions(**perms):
    """
    A check that checks if the user has the required permissions to run the command.
    Args:
        perms: The permissions to check for.
        is_bot_manager: Whether to check if the user has the bot manager role configured for the guild as well.

    Returns:
        A check function.
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        # Check if the user has the required permissions.
        if not interaction.guild_id:  # If the command is executed in DMs, the user has all permissions.
            return True
        member: discord.Member = interaction.guild.get_member(interaction.user.id)
        is_manager_perm = perms.pop("is_bot_manager", None)
        missing_perms = check_missing_perms(member.guild_permissions, discord.Permissions(**perms))

        if is_manager_perm is not None:
            perms["is_bot_manager"] = is_manager_perm

        if is_manager_perm:
            manager_role_id = await interaction.client.db.get_guild_manager_role(interaction.guild_id)
            if manager_role_id is not None:
                if manager_role_id not in [role.id for role in interaction.user.roles] and missing_perms:
                    raise app_commands.MissingRole(manager_role_id)
                return True  # If the user has the bot manager role, return True.
        if missing_perms:
            raise app_commands.MissingPermissions(missing_perms)
        return True

    return app_commands.check(predicate)


def bot_has_permissions(**perms):
    """
    A check that checks if the bot has the required permissions to run the command.
    Args:
        perms: The permissions to check for.

    Returns:
        A check function.
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        # Check if the bot has the required permissions.
        if not interaction.guild_id:
            return True
        if missing_perms := check_missing_perms(interaction.guild.me.guild_permissions, discord.Permissions(**perms)):
            raise app_commands.BotMissingPermissions(missing_perms)
        return True

    return app_commands.check(predicate)


def has_premium(*, dm_only: bool = True):
    """
    Check if the user is a patreon.
    Args:
        dm_only: Only applies the check if the interaction is in a DM channel.

    Returns:
        A check function.

    Raises:
        PremiumFeatureOnly: If the user is not a patreon.
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
