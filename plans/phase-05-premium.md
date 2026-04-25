# Phase 5 — Premium subsystem

> **Recommended model:** Claude **Opus 4.7** at **high** reasoning effort.
> Three independent sources, async polling task, cache invalidation, and
> a custom check decorator with a global error handler — easy to get
> wrong. Worth Opus's stronger reasoning. After this lands, future
> sessions can revert to Sonnet.

## Goal

Implement the three-source premium gate described in the master plan:
DB grants, Patreon active patrons, Discord App Subscriptions. Provide
`@checks.has_premium(*, dm_only=False)` for cogs to apply.

## Depends on

- Phase 3 (`db/premium_grants.py`, `db/patreon_links.py`)
- Phase 4 (`bot.py` to attach the service)
- `src/manhwa_bot/config.py` already exposes `PremiumConfig` with
  `discord` and `patreon` sub-sections.

## Reference docs

Use `mcp__plugin_context7_context7` to fetch current docs for these — APIs
have changed between discord.py releases:

- `discord.Entitlement`, `discord.SKU`, `interaction.entitlements`,
  `bot.fetch_entitlements`, `bot.fetch_skus`, `discord.ButtonStyle.premium`
- Event listeners: `on_entitlement_create`, `on_entitlement_update`,
  `on_entitlement_delete`
- Patreon API v2: `/api/oauth2/v2/campaigns/{id}/members` with
  `include=user,currently_entitled_tiers` and
  `fields[user]=social_connections`

## Files to create

```
src/manhwa_bot/premium/
├── __init__.py
├── service.py
├── grants.py
├── patreon.py
└── discord_entitlements.py
src/manhwa_bot/checks.py
src/manhwa_bot/ui/upgrade_embed.py
tests/
├── test_premium_grants_service.py
├── test_premium_discord_entitlements.py
├── test_premium_patreon.py
└── test_premium_orchestrator.py
```

## Module specs

### `premium/grants.py` — `GrantsService`

Thin layer over `db.premium_grants.PremiumGrantStore` that adds:
- `is_active(scope, target_id) -> bool`
- A periodic sweep task started by the orchestrator that calls
  `sweep_expired()` every 60 seconds and logs revocations.
- Duration parser: `"7d"`, `"48h"`, `"1mo"`, `"permanent"`, ISO timestamp.

### `premium/patreon.py` — `PatreonClient`

- Pure aiohttp client; no discord.py dependency.
- Constructor: `PatreonClient(config: PatreonPremiumConfig, store: PatreonLinkStore, session_factory)`.
- `async def start(self)`: spawns a background task that calls `refresh()`
  every `poll_interval_seconds`. First call runs immediately on startup.
- `async def stop(self)`: cancels and awaits the task.
- `async def refresh(self) -> int`: returns count of active patrons
  written. Implementation:
  - GET `https://www.patreon.com/api/oauth2/v2/campaigns/{campaign_id}/members`
  - Query params: `include=user,currently_entitled_tiers`,
    `fields[member]=patron_status,currently_entitled_amount_cents,last_charge_status,last_charge_date,full_name`,
    `fields[user]=social_connections`,
    `page[count]=1000`
  - Auth: `Authorization: Bearer {access_token}`
  - Paginate via `links.next` cursor.
  - For each member with `attributes.patron_status == "active_patron"`:
    - Resolve `relationships.user.data.id` → look up the included `user`.
    - Read `attributes.social_connections.discord.user_id`. If null, skip
      (no Discord link).
    - If `required_tier_ids` is non-empty, verify the member's
      `currently_entitled_tiers` overlaps — else skip.
    - Upsert `patreon_links` with `expires_at = now + freshness_seconds`.
  - After the full sweep, optionally delete rows whose `expires_at < now`
    (stale patrons).
  - On any HTTP error: log, increment a backoff, return 0; do NOT clear
    the cache (stale-but-present is better than empty).
- `is_premium(discord_user_id) -> bool` reads only from the cache table
  via `store.is_active(...)`. No live API calls per check.

### `premium/discord_entitlements.py` — `DiscordEntitlementsService`

Stateful in-memory cache keyed by `(scope, id)`. Bot-attached.

- `async def warm(self, bot)`: on ready, calls `bot.fetch_entitlements(exclude_ended=True)`
  and stores into the cache. Also `bot.fetch_skus()` to validate SKU IDs.
- Listeners (registered as cog-style listeners in `service.py` setup):
  `on_entitlement_create`, `on_entitlement_update` add/replace; `on_entitlement_delete` removes.
- `def is_user_premium(user_id, configured_user_skus) -> bool`: walks the
  cache for active user-scoped entitlements.
- `def is_guild_premium(guild_id, configured_guild_skus) -> bool`: same for guild.
- `def from_interaction(interaction, configured_user_skus, configured_guild_skus, *, dm_only) -> bool`:
  inspects `interaction.entitlements` directly (always more authoritative for
  the invoking context than the cache).

### `premium/service.py` — `PremiumService`

The orchestrator. Wires the three sources together.

```python
class PremiumService:
    config: PremiumConfig
    grants: GrantsService
    patreon: PatreonClient
    discord_ents: DiscordEntitlementsService
    bot: ManhwaBot   # for owner_ids

    async def is_premium(
        self,
        *,
        user_id: int,
        guild_id: int | None,
        interaction: discord.Interaction | None = None,
        dm_only: bool = False,
    ) -> tuple[bool, str | None]:
        ...
```

Decision order (return `(True, reason)` on first match):

1. `not config.enabled` → `(True, "disabled")`.
2. `config.owner_bypass` and `user_id in self.bot.owner_ids` → `(True, "owner")`.
3. `await self.grants.is_active("user", user_id)` → `(True, "grant_user")`.
4. If not `dm_only` and `guild_id`: `await self.grants.is_active("guild", guild_id)` → `(True, "grant_guild")`.
5. `await self.patreon.is_premium(user_id)` (if patreon enabled) → `(True, "patreon")`.
6. Discord entitlements: prefer `interaction.entitlements` if provided,
   else cache lookup → `(True, "discord_user")` or `(True, "discord_guild")`.
7. Fallthrough → `(False, None)`.

When `config.log_decisions` is true, log every call's inputs and reason.

### `checks.py` — `has_premium`

```python
def has_premium(*, dm_only: bool = False):
    async def predicate(interaction: discord.Interaction) -> bool:
        bot: ManhwaBot = interaction.client  # type: ignore[assignment]
        ok, _reason = await bot.premium.is_premium(
            user_id=interaction.user.id,
            guild_id=interaction.guild.id if interaction.guild else None,
            interaction=interaction,
            dm_only=dm_only,
        )
        if not ok:
            raise app_commands.CheckFailure("premium_required")
        return True
    return app_commands.check(predicate)
```

Plus a global tree error handler (registered in `bot.py`):

```python
@bot.tree.error
async def on_app_command_error(interaction, error):
    if isinstance(error, app_commands.CheckFailure) and str(error) == "premium_required":
        embed = build_upgrade_embed(bot.config.premium)
        view = build_upgrade_view(bot.config.premium)  # Patreon link button + Discord premium button
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return
    # rethrow / log for other errors
    raise error
```

For prefix commands, also handle `commands.CheckFailure` with the same embed
in a `on_command_error` listener (used by the dev cog only, but for parity).

### `ui/upgrade_embed.py`

- `build_upgrade_embed(config: PremiumConfig) -> discord.Embed` — title
  "Premium required", description listing the three upgrade paths.
- `build_upgrade_view(config: PremiumConfig) -> discord.ui.View` —
  - Row 1: link button to Patreon (`config.patreon.pledge_url`) if non-empty.
  - Row 2: `discord.ui.Button(style=ButtonStyle.premium, sku_id=...)`
    for each SKU in `config.discord.user_sku_ids` (max 5; Discord caps).
  - If `config.discord.upgrade_url` is set, also a link button to it.

### Bot wiring (Phase 4 update)

In `bot.setup_hook`, after the DB pool is open and migrations run:

```python
self.grants = GrantsService(...)
self.patreon = PatreonClient(...)
self.discord_ents = DiscordEntitlementsService(...)
self.premium = PremiumService(self, ...)
await self.patreon.start()  # if enabled
self.add_listener(self.discord_ents.on_entitlement_create, "on_entitlement_create")
self.add_listener(self.discord_ents.on_entitlement_update, "on_entitlement_update")
self.add_listener(self.discord_ents.on_entitlement_delete, "on_entitlement_delete")
```

In `on_ready`, call `await self.discord_ents.warm(self)` once.
In `close`, call `await self.patreon.stop()`.

## Tests

- `test_premium_grants_service.py` — covered partially by Phase 3's
  `test_db_premium_grants.py`; here add tests for the duration parser
  (`"7d"` → 7 days from now, `"permanent"` → None expiry, ISO strings).
- `test_premium_discord_entitlements.py` — synthetic `Entitlement`-shaped
  objects via simple `SimpleNamespace` fakes; assert each branch
  (user/guild scope, expired, missing SKU, listener add/remove).
- `test_premium_patreon.py` — fake aiohttp test server returning a fixed
  `members` page (1 active patron with social_connection.discord, 1 active
  without, 1 declined). Verify upsert count = 1, pagination is followed,
  required_tier_ids filter narrows correctly, network errors don't clear
  cache.
- `test_premium_orchestrator.py` — mock the 3 sources; assert priority
  order (owner > grant_user > grant_guild > patreon > discord_user >
  discord_guild) and `dm_only` skips guild scopes and discord_guild.

## Verification

```bash
python -m ruff check src/manhwa_bot/premium src/manhwa_bot/checks.py src/manhwa_bot/ui/upgrade_embed.py tests/test_premium_*.py
python -m ruff format --check src/manhwa_bot/premium src/manhwa_bot/checks.py src/manhwa_bot/ui/upgrade_embed.py tests/test_premium_*.py
python -m pytest tests/test_premium_*.py -v
```

Manual:
- Start bot, no entitlements/grants/Patreon link. Apply `@has_premium` to a
  test slash command; invoke → see the upgrade embed.
- `/dev premium grant scope:user target:<self> duration:1h` (Phase 13
  command — for now, INSERT manually via sqlite CLI). Re-invoke → command
  passes. (Phase 13 wires the slash command; Phase 5 just builds the
  service layer.)

## Commit message

```
Add three-source premium gate

- DB-backed grants (manual issuance with optional expiry, periodic sweep)
- Patreon active-patron polling with social-connection lookup
- Discord App Subscription entitlements with cache + interaction-direct lookup
- PremiumService orchestrator with explicit decision order
- @checks.has_premium decorator + global tree error handler with
  upgrade embed (Patreon link + Discord premium SKU button)
- Tests for each source in isolation and the orchestrator priority
```
