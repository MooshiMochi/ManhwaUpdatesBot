"""Premium subsystem: three-source gate (DB grants, Patreon, Discord entitlements)."""

from .discord_entitlements import DiscordEntitlementsService
from .grants import GrantsService, parse_duration
from .patreon import PatreonClient
from .service import PremiumDecision, PremiumService

__all__ = [
    "DiscordEntitlementsService",
    "GrantsService",
    "PatreonClient",
    "PremiumDecision",
    "PremiumService",
    "parse_duration",
]
