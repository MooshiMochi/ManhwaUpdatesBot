"""PatreonClient — periodic poll of campaign members; cache active patrons."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from ..config import PatreonPremiumConfig
from ..db.patreon_links import PatreonLinkStore

_log = logging.getLogger(__name__)

_PATREON_BASE = "https://www.patreon.com/api/oauth2/v2"
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_DEFAULT_PAGE_SIZE = 1000


class PatreonClient:
    """Polls Patreon for active patrons and stores Discord links in the cache."""

    def __init__(
        self,
        config: PatreonPremiumConfig,
        store: PatreonLinkStore,
        session_factory: Callable[[], aiohttp.ClientSession] | None = None,
        base_url: str = _PATREON_BASE,
    ) -> None:
        self._config = config
        self._store = store
        self._base_url = base_url.rstrip("/")
        self._session_factory = session_factory or aiohttp.ClientSession
        self._task: asyncio.Task[None] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled and self._config.access_token and self._config.campaign_id)

    async def is_premium(self, discord_user_id: int) -> bool:
        if not self.enabled:
            return False
        return await self._store.is_active(discord_user_id)

    async def start(self) -> None:
        if not self.enabled:
            _log.info("Patreon premium source disabled — skipping poll")
            return
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._poll_loop(), name="premium-patreon-poll")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError, Exception:
            pass

    async def _poll_loop(self) -> None:
        while True:
            try:
                count = await self.refresh()
                _log.debug("Patreon refresh wrote %d active patrons", count)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception("Patreon refresh failed")
            try:
                await asyncio.sleep(self._config.poll_interval_seconds)
            except asyncio.CancelledError:
                raise

    async def refresh(self) -> int:
        """Walk every page of campaign members; upsert active patrons. Returns count."""
        if not self.enabled:
            return 0
        url = f"{self._base_url}/campaigns/{self._config.campaign_id}/members"
        params: dict[str, str] = {
            "include": "user,currently_entitled_tiers",
            "fields[member]": (
                "patron_status,currently_entitled_amount_cents,"
                "last_charge_status,last_charge_date,full_name"
            ),
            "fields[user]": "social_connections",
            "page[count]": str(_DEFAULT_PAGE_SIZE),
        }
        headers = {"Authorization": f"Bearer {self._config.access_token}"}

        try:
            session = self._session_factory()
        except Exception:
            _log.exception("Failed to create aiohttp session for Patreon refresh")
            return 0

        active_count = 0
        next_url: str | None = url
        next_params: dict[str, str] | None = params
        try:
            async with session:
                while next_url:
                    try:
                        async with session.get(
                            next_url, params=next_params, headers=headers
                        ) as resp:
                            if resp.status != 200:
                                body = await resp.text()
                                _log.warning(
                                    "Patreon API returned %d for %s: %s",
                                    resp.status,
                                    next_url,
                                    body[:500],
                                )
                                return 0
                            payload = await resp.json()
                    except aiohttp.ClientError:
                        _log.exception("Patreon HTTP error while fetching %s", next_url)
                        return 0

                    active_count += await self._process_page(payload)

                    links = payload.get("links") or {}
                    raw_next = links.get("next")
                    if not raw_next:
                        next_url = None
                        next_params = None
                    else:
                        next_url = raw_next
                        # Patreon embeds the cursor in `links.next`; clear params to avoid
                        # double-encoding them.
                        next_params = None
        except Exception:
            _log.exception("Unexpected error during Patreon refresh")
            return 0

        return active_count

    async def _process_page(self, payload: dict[str, Any]) -> int:
        users_by_id: dict[str, dict[str, Any]] = {}
        for entry in payload.get("included") or []:
            if entry.get("type") == "user":
                users_by_id[str(entry.get("id"))] = entry

        required_tiers = set(self._config.required_tier_ids)
        now = datetime.now(tz=UTC)
        expires_at = (now + timedelta(seconds=self._config.freshness_seconds)).strftime(
            _TIMESTAMP_FORMAT
        )
        refreshed_at = now.strftime(_TIMESTAMP_FORMAT)

        count = 0
        for member in payload.get("data") or []:
            if member.get("type") != "member":
                continue
            attrs = member.get("attributes") or {}
            if attrs.get("patron_status") != "active_patron":
                continue

            relationships = member.get("relationships") or {}
            user_ref = ((relationships.get("user") or {}).get("data")) or {}
            patreon_user_id = str(user_ref.get("id") or "")
            if not patreon_user_id:
                continue

            tier_refs = ((relationships.get("currently_entitled_tiers") or {}).get("data")) or []
            tier_ids = [str(t.get("id")) for t in tier_refs if t.get("id") is not None]
            if required_tiers and not (required_tiers & set(tier_ids)):
                continue

            user_entry = users_by_id.get(patreon_user_id)
            if not user_entry:
                continue
            social = ((user_entry.get("attributes") or {}).get("social_connections")) or {}
            discord_link = social.get("discord") or {}
            discord_user_id_raw = discord_link.get("user_id")
            if not discord_user_id_raw:
                continue
            try:
                discord_user_id = int(discord_user_id_raw)
            except TypeError, ValueError:
                continue

            cents = int(attrs.get("currently_entitled_amount_cents") or 0)
            await self._store.upsert(
                discord_user_id=discord_user_id,
                patreon_user_id=patreon_user_id,
                tier_ids=json.dumps(tier_ids),
                cents=cents,
                refreshed_at=refreshed_at,
                expires_at=expires_at,
            )
            count += 1

        return count
