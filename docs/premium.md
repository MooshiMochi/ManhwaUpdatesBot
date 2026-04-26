# Premium Setup

Premium access can come from any one of three sources: manual database grants, Patreon active patrons, or Discord App Subscription entitlements. The check path is local and cached where possible so commands do not make external API calls per interaction.

## Discord App Subscriptions

Use Discord's official monetization docs as the source of truth:

- Enabling monetization: https://docs.discord.com/developers/monetization/enabling-monetization
- SKU resource: https://docs.discord.com/developers/docs/monetization/skus
- Entitlement resource: https://docs.discord.com/developers/docs/monetization/entitlements

High-level setup:

1. Put the Discord application under a developer team that is eligible for monetization.
2. Enable monetization in the Developer Portal.
3. Create subscription SKUs for user-scoped and/or guild-scoped premium.
4. Use subscription SKUs with type `SUBSCRIPTION` (`type: 5`), not the generated subscription group SKU.
5. Copy the SKU IDs into `config.toml`.

```toml
[premium.discord]
enabled = true
user_sku_ids = [123456789012345678]
guild_sku_ids = [234567890123456789]
upgrade_url = "https://discord.com/application-directory/<app_id>/store"
```

User SKUs follow the user across guilds. Guild SKUs apply only inside the guild where the entitlement exists. In DMs, only user-scoped premium sources qualify.

## Patreon

Patreon integration uses the v2 API and caches campaign members that have linked Discord in their Patreon social connections. Patreon API reference: https://docs.patreon.com/

Setup:

1. Create or open a Patreon OAuth client.
2. Generate an access token with access to campaign members.
3. Find the campaign ID from the Patreon API or creator dashboard.
4. Put the access token in `.env`, never in `config.toml`.
5. Configure campaign settings in `config.toml`.

```env
PATREON_ACCESS_TOKEN=...
```

```toml
[premium.patreon]
enabled = true
campaign_id = 7698994
poll_interval_seconds = 600
freshness_seconds = 1800
required_tier_ids = []
pledge_url = "https://www.patreon.com/<creator>"
```

Leave `required_tier_ids` empty to accept any active patron. Set it to one or more Patreon tier IDs when only specific tiers should unlock premium.

The bot polls members with `include=user,currently_entitled_tiers`, checks `patron_status == "active_patron"`, reads the linked Discord user ID from the included user social connections, and stores a local cache row. If Patreon is temporarily unavailable, existing fresh cache entries continue to work until their freshness window expires.

## Manual grants

Owners can grant premium without Patreon or Discord billing. This is useful for support, early supporters, testing, and free trials.

Examples:

```text
@ManhwaUpdatesBot d premium grant user 123456789012345678 30d "trial"
@ManhwaUpdatesBot d premium grant guild 234567890123456789 permanent "partner guild"
@ManhwaUpdatesBot d premium revoke user 123456789012345678
@ManhwaUpdatesBot d premium list
@ManhwaUpdatesBot d premium check @SomeUser
```

Supported durations include hours, days, months, `permanent`, and explicit ISO timestamps. Expired grants are ignored and can be swept by the premium grant service.

## Auditing access

Use owner commands to inspect why a user qualifies:

```text
@ManhwaUpdatesBot d premium check @SomeUser
@ManhwaUpdatesBot d premium list active
@ManhwaUpdatesBot d premium patreon refresh
```

The premium orchestrator checks sources in this order:

1. Owner bypass, if enabled.
2. Manual DB grant for the user or guild.
3. Patreon cache row for the user.
4. Discord entitlement for the user or guild.

The first matching source is returned as the decision reason. Enable `[premium].log_decisions = true` while debugging support tickets.

## Security notes

- Keep `DISCORD_BOT_TOKEN`, `CRAWLER_API_KEY`, and `PATREON_ACCESS_TOKEN` in `.env` only.
- Do not commit `config.toml` if it contains deployment-specific IDs you consider private.
- Rotate Patreon and Discord tokens if they appear in logs, screenshots, or chat transcripts.
- Treat Discord SKU IDs as public configuration, not secrets.
