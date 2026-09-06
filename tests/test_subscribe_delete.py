from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from manhwa_bot import autocomplete
from manhwa_bot.cogs.subscriptions import SubscriptionsCog
from manhwa_bot.db.migrate import apply_pending
from manhwa_bot.db.pool import DbPool


def _text(view):
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )


@pytest.mark.parametrize(
    "mode",
    [
        "single",
        "all",
        "all_forbidden",
        "forbidden",
        "http_error",
        "absent",
        "deleted",
        "dm",
        "untracked",
        "no_role",
    ],
)
def test_delete_subscription(tmp_path, monkeypatch, mode):
    async def run():
        pool = await DbPool.open(str(tmp_path / "test.db"))
        await apply_pending(pool)
        try:
            cog = SubscriptionsCog(SimpleNamespace(db=pool))
            guild_id = 0 if mode == "dm" else 100
            bulk = mode.startswith("all")
            failure = mode in {"forbidden", "all_forbidden", "http_error"}
            await cog._tracked.upsert_series(
                "asura",
                "absolute-necromancer-123",
                "https://example.test/series",
                "Absolute Necromancer",
            )
            if mode not in {"dm", "untracked"}:
                await cog._tracked.add_to_guild(guild_id, "asura", "absolute-necromancer-123")
                await cog._tracked.update_ping_role(
                    guild_id,
                    "asura",
                    "absolute-necromancer-123",
                    None if mode == "no_role" else 789,
                )
            await cog._subs.subscribe(200, guild_id, "asura", "absolute-necromancer-123")
            await cog._subs.subscribe(201, guild_id, "asura", "absolute-necromancer-123")
            await cog._subs.subscribe(200, 101, "asura", "absolute-necromancer-123")
            role = SimpleNamespace(id=789, mention="<@&789>")
            member = Mock(spec=discord.Member)
            member.id = 200
            member.roles = [] if mode == "absent" else [role]
            member.remove_roles = AsyncMock()
            if failure:
                error = discord.HTTPException if mode == "http_error" else discord.Forbidden
                member.remove_roles.side_effect = error(
                    SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions"
                )
            interaction = SimpleNamespace(
                guild_id=guild_id or None,
                guild=None
                if mode == "dm"
                else SimpleNamespace(
                    id=guild_id, get_role=Mock(return_value=None if mode == "deleted" else role)
                ),
                user=member,
                response=SimpleNamespace(defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()),
                edit_original_response=AsyncMock(),
            )
            if bulk:
                confirm = SimpleNamespace(value=True, bind_message=Mock(), wait=AsyncMock())
                monkeypatch.setattr(
                    "manhwa_bot.cogs.subscriptions.ConfirmLayoutView", Mock(return_value=confirm)
                )
            await cog.subscribe_delete.callback(
                cog, interaction, "*" if bulk else "asura:absolute-necromancer-123"
            )
            if mode in {"single", "all", "all_forbidden", "forbidden", "http_error"}:
                member.remove_roles.assert_awaited_once_with(
                    role, reason="ManhwaUpdatesBot: /subscribe delete"
                )
            else:
                member.remove_roles.assert_not_awaited()
            assert (
                await cog._subs.is_subscribed(200, guild_id, "asura", "absolute-necromancer-123")
                == failure
            )
            assert await cog._subs.is_subscribed(201, guild_id, "asura", "absolute-necromancer-123")
            assert await cog._subs.is_subscribed(200, 101, "asura", "absolute-necromancer-123")
            response = interaction.edit_original_response if bulk else interaction.followup.send
            text = _text(response.call_args.kwargs["view"])
            if not bulk:
                assert "Absolute Necromancer" in text
                assert "absolute-necromancer-123" not in text
            if failure:
                assert "permissions" in text
                assert "Successfully unsubscribed" not in text
            if mode == "single":
                assert role.mention in text
        finally:
            await pool.close()

    asyncio.run(run())


@pytest.mark.parametrize("query", ["", "Absolute Necromancer", "(asu Absolute"])
def test_subscription_choices_use_titles(tmp_path, query):
    async def run():
        pool = await DbPool.open(str(tmp_path / "test.db"))
        await apply_pending(pool)
        try:
            cog = SubscriptionsCog(SimpleNamespace(db=pool))
            await cog._tracked.upsert_series(
                "asura",
                "absolute-necromancer-123",
                "https://example.test/series",
                "Absolute Necromancer",
            )
            await cog._subs.subscribe(200, 100, "asura", "absolute-necromancer-123")
            interaction = SimpleNamespace(
                client=cog.bot, guild=SimpleNamespace(id=100), user=SimpleNamespace(id=200)
            )
            choices = await autocomplete.user_subscribed_manga_with_all(interaction, query)
            assert [(c.name, c.value) for c in choices if c.value != "*"] == [
                ("(asura) Absolute Necromancer", "asura:absolute-necromancer-123")
            ]
        finally:
            await pool.close()

    asyncio.run(run())
