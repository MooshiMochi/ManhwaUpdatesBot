"""Tests for PatreonClient against a fake aiohttp test server."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

import aiohttp
from aiohttp import web

from manhwa_bot.config import PatreonPremiumConfig
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.patreon_links import PatreonLinkStore
from manhwa_bot.db.pool import DbPool
from manhwa_bot.premium.patreon import PatreonClient


def _config(
    *,
    enabled: bool = True,
    access_token: str = "test-token",
    campaign_id: int = 1234,
    required_tier_ids: tuple[str, ...] = (),
    poll_interval_seconds: int = 600,
) -> PatreonPremiumConfig:
    return PatreonPremiumConfig(
        enabled=enabled,
        campaign_id=campaign_id,
        poll_interval_seconds=poll_interval_seconds,
        freshness_seconds=1800,
        required_tier_ids=required_tier_ids,
        pledge_url="",
        access_token=access_token,
    )


async def _open_store(tmp: str) -> tuple[DbPool, PatreonLinkStore]:
    pool = await DbPool.open(str(Path(tmp) / "test.db"))
    await apply_pending(pool)
    return pool, PatreonLinkStore(pool)


async def _start_server(
    handler: Callable[[web.Request], Awaitable[web.Response]],
) -> tuple[web.AppRunner, str]:
    app = web.Application()
    app.router.add_get("/campaigns/{campaign_id}/members", handler)
    app.router.add_get("/page2", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets  # type: ignore[union-attr]
    assert sockets is not None
    port = sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def _members_payload(
    *,
    members: list[dict],
    users: list[dict],
    next_url: str | None = None,
) -> dict:
    return {
        "data": members,
        "included": users,
        "links": {"next": next_url} if next_url else {},
    }


def _active_member(
    *,
    member_id: str,
    user_id: str,
    discord_user_id: str | None,
    tier_ids: tuple[str, ...] = (),
    cents: int = 500,
) -> tuple[dict, dict]:
    member = {
        "id": member_id,
        "type": "member",
        "attributes": {
            "patron_status": "active_patron",
            "currently_entitled_amount_cents": cents,
            "last_charge_status": "Paid",
            "last_charge_date": "2030-01-01T00:00:00",
            "full_name": f"User {member_id}",
        },
        "relationships": {
            "user": {"data": {"id": user_id, "type": "user"}},
            "currently_entitled_tiers": {"data": [{"id": t, "type": "tier"} for t in tier_ids]},
        },
    }
    user_attributes: dict = {"social_connections": {}}
    if discord_user_id is not None:
        user_attributes["social_connections"] = {"discord": {"user_id": discord_user_id}}
    user = {
        "id": user_id,
        "type": "user",
        "attributes": user_attributes,
    }
    return member, user


def _declined_member(member_id: str, user_id: str) -> tuple[dict, dict]:
    member = {
        "id": member_id,
        "type": "member",
        "attributes": {
            "patron_status": "declined_patron",
            "currently_entitled_amount_cents": 0,
        },
        "relationships": {
            "user": {"data": {"id": user_id, "type": "user"}},
            "currently_entitled_tiers": {"data": []},
        },
    }
    user = {"id": user_id, "type": "user", "attributes": {"social_connections": {}}}
    return member, user


def test_refresh_writes_only_active_with_discord_link() -> None:
    async def _run() -> None:
        m_active_linked, u_active_linked = _active_member(
            member_id="m1", user_id="u1", discord_user_id="111111", tier_ids=("t1",)
        )
        m_active_no_link, u_active_no_link = _active_member(
            member_id="m2", user_id="u2", discord_user_id=None
        )
        m_declined, u_declined = _declined_member("m3", "u3")

        async def handler(_req: web.Request) -> web.Response:
            payload = _members_payload(
                members=[m_active_linked, m_active_no_link, m_declined],
                users=[u_active_linked, u_active_no_link, u_declined],
            )
            return web.Response(text=json.dumps(payload), content_type="application/json")

        runner, base_url = await _start_server(handler)
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _open_store(tmp)
            try:
                client = PatreonClient(_config(), store, base_url=base_url)
                count = await client.refresh()
                assert count == 1
                assert await store.is_active(111111) is True
            finally:
                await pool.close()
                await runner.cleanup()

    asyncio.run(_run())


def test_refresh_follows_pagination() -> None:
    async def _run() -> None:
        m_a, u_a = _active_member(member_id="m1", user_id="u1", discord_user_id="111111")
        m_b, u_b = _active_member(member_id="m2", user_id="u2", discord_user_id="222222")

        page1_seen: list[bool] = []

        async def handler(req: web.Request) -> web.Response:
            if req.path.endswith("/page2"):
                payload = _members_payload(members=[m_b], users=[u_b])
            else:
                page1_seen.append(True)
                next_url = f"http://127.0.0.1:{req.url.port}/page2"
                payload = _members_payload(members=[m_a], users=[u_a], next_url=next_url)
            return web.Response(text=json.dumps(payload), content_type="application/json")

        runner, base_url = await _start_server(handler)
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _open_store(tmp)
            try:
                client = PatreonClient(_config(), store, base_url=base_url)
                count = await client.refresh()
                assert count == 2
                assert page1_seen == [True]
                assert await store.is_active(111111) is True
                assert await store.is_active(222222) is True
            finally:
                await pool.close()
                await runner.cleanup()

    asyncio.run(_run())


def test_refresh_filters_by_required_tier_ids() -> None:
    async def _run() -> None:
        m_in, u_in = _active_member(
            member_id="m1", user_id="u1", discord_user_id="111111", tier_ids=("gold",)
        )
        m_out, u_out = _active_member(
            member_id="m2", user_id="u2", discord_user_id="222222", tier_ids=("bronze",)
        )

        async def handler(_req: web.Request) -> web.Response:
            payload = _members_payload(members=[m_in, m_out], users=[u_in, u_out])
            return web.Response(text=json.dumps(payload), content_type="application/json")

        runner, base_url = await _start_server(handler)
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _open_store(tmp)
            try:
                client = PatreonClient(
                    _config(required_tier_ids=("gold",)), store, base_url=base_url
                )
                count = await client.refresh()
                assert count == 1
                assert await store.is_active(111111) is True
                assert await store.is_active(222222) is False
            finally:
                await pool.close()
                await runner.cleanup()

    asyncio.run(_run())


def test_http_error_does_not_clear_cache() -> None:
    async def _run() -> None:
        async def handler(_req: web.Request) -> web.Response:
            return web.Response(status=502, text="bad gateway")

        runner, base_url = await _start_server(handler)
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _open_store(tmp)
            try:
                # Pre-seed the cache so we can prove it was not wiped.
                await store.upsert(
                    discord_user_id=999,
                    patreon_user_id="u9",
                    tier_ids="[]",
                    cents=0,
                    refreshed_at="2030-01-01 00:00:00",
                    expires_at="2099-01-01 00:00:00",
                )
                client = PatreonClient(_config(), store, base_url=base_url)
                count = await client.refresh()
                assert count == 0
                assert await store.is_active(999) is True
            finally:
                await pool.close()
                await runner.cleanup()

    asyncio.run(_run())


def test_disabled_client_is_noop() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _open_store(tmp)
            try:
                client = PatreonClient(_config(enabled=False), store)
                assert client.enabled is False
                assert await client.refresh() == 0
                await client.start()  # no-op
                await client.stop()
                assert await client.is_premium(111) is False

                client2 = PatreonClient(_config(access_token=""), store)
                assert client2.enabled is False
            finally:
                await pool.close()

    asyncio.run(_run())


def test_session_factory_is_used() -> None:
    """The injected session_factory must be honoured (covers the dependency hook)."""

    async def _run() -> None:
        async def handler(_req: web.Request) -> web.Response:
            return web.Response(
                text=json.dumps(_members_payload(members=[], users=[])),
                content_type="application/json",
            )

        runner, base_url = await _start_server(handler)
        with tempfile.TemporaryDirectory() as tmp:
            pool, store = await _open_store(tmp)
            try:
                created: list[aiohttp.ClientSession] = []

                def factory() -> aiohttp.ClientSession:
                    s = aiohttp.ClientSession()
                    created.append(s)
                    return s

                client = PatreonClient(_config(), store, session_factory=factory, base_url=base_url)
                await client.refresh()
                assert len(created) == 1
                assert created[0].closed is True  # closed by `async with session`
            finally:
                await pool.close()
                await runner.cleanup()

    asyncio.run(_run())
