"""Link-button views (support server, invite, github, ToS, privacy, patreon, ko-fi).

Mirrors the v1 ``SupportView`` layout: row 0 has Support/Invite/GitHub/TOS/Privacy,
row 1 has Patreon/Ko-fi.
"""

from __future__ import annotations

import discord

DEFAULT_SUPPORT_URL = "https://discord.gg/TYkw8VBZkr"
DEFAULT_INVITE_URL = (
    "https://discord.com/api/oauth2/authorize?client_id=1031998059447590955"
    "&permissions=412854111296&scope=bot%20applications.commands"
)
DEFAULT_GITHUB_URL = "https://github.com/MooshiMochi/ManhwaUpdatesBot"
DEFAULT_TOS_URL = "https://github.com/MooshiMochi/ManhwaUpdatesBot/blob/master/.discord/terms.md"
DEFAULT_PRIVACY_URL = (
    "https://github.com/MooshiMochi/ManhwaUpdatesBot/blob/master/.discord/privacy.md"
)
DEFAULT_PATREON_URL = "https://www.patreon.com/mooshi69"
DEFAULT_KOFI_URL = "https://ko-fi.com/mooshi69"


class SupportView(discord.ui.View):
    """Five primary links on row 0, two donation links on row 1."""

    def __init__(
        self,
        *,
        support_url: str | None = DEFAULT_SUPPORT_URL,
        invite_url: str | None = DEFAULT_INVITE_URL,
        github_url: str | None = DEFAULT_GITHUB_URL,
        tos_url: str | None = DEFAULT_TOS_URL,
        privacy_url: str | None = DEFAULT_PRIVACY_URL,
        patreon_url: str | None = DEFAULT_PATREON_URL,
        kofi_url: str | None = DEFAULT_KOFI_URL,
    ) -> None:
        super().__init__(timeout=None)
        if support_url:
            self.add_item(discord.ui.Button(label="Support Server", url=support_url, row=0))
        if invite_url:
            self.add_item(discord.ui.Button(label="Invite", url=invite_url, row=0))
        if github_url:
            self.add_item(discord.ui.Button(label="GitHub", url=github_url, row=0))
        if tos_url:
            self.add_item(discord.ui.Button(label="TOS", url=tos_url, row=0))
        if privacy_url:
            self.add_item(discord.ui.Button(label="Privacy", url=privacy_url, row=0))
        if patreon_url:
            self.add_item(discord.ui.Button(label="Patreon", url=patreon_url, row=1))
        if kofi_url:
            self.add_item(discord.ui.Button(label="Ko-fi", url=kofi_url, row=1))


class PatreonView(discord.ui.View):
    def __init__(
        self,
        *,
        patreon_url: str = DEFAULT_PATREON_URL,
        kofi_url: str = DEFAULT_KOFI_URL,
    ) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Patreon", url=patreon_url))
        self.add_item(discord.ui.Button(label="Ko-fi", url=kofi_url))
