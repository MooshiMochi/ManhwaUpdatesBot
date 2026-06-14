from __future__ import annotations

from types import SimpleNamespace

from manhwa_bot.cogs.updates import UpdatesCog

_compose_ping = UpdatesCog._compose_ping


class _Guild:
    """Minimal guild stub: only the given role ids resolve."""

    def __init__(self, existing_role_ids: set[int]) -> None:
        self._existing = existing_role_ids

    def get_role(self, role_id: int):
        return object() if role_id in self._existing else None


def test_custom_role_used_when_it_still_exists() -> None:
    guild = _Guild({111})
    row = SimpleNamespace(ping_role_id=111)
    settings = SimpleNamespace(default_ping_role_id=222)
    assert _compose_ping(guild, row, settings) == "<@&111>"


def test_deleted_custom_role_falls_back_to_default() -> None:
    # The reported bug: a custom ping role was deleted, so its dangling id
    # rendered as "@unknown-role". It must fall back to the default ping role.
    guild = _Guild({222})  # 111 (custom) no longer exists
    row = SimpleNamespace(ping_role_id=111)
    settings = SimpleNamespace(default_ping_role_id=222)
    assert _compose_ping(guild, row, settings) == "<@&222>"


def test_both_roles_deleted_yields_no_ping() -> None:
    guild = _Guild(set())
    row = SimpleNamespace(ping_role_id=111)
    settings = SimpleNamespace(default_ping_role_id=222)
    assert _compose_ping(guild, row, settings) == ""


def test_no_custom_role_uses_default() -> None:
    guild = _Guild({222})
    row = SimpleNamespace(ping_role_id=None)
    settings = SimpleNamespace(default_ping_role_id=222)
    assert _compose_ping(guild, row, settings) == "<@&222>"


def test_no_roles_configured_yields_no_ping() -> None:
    guild = _Guild({1, 2, 3})
    row = SimpleNamespace(ping_role_id=None)
    settings = SimpleNamespace(default_ping_role_id=None)
    assert _compose_ping(guild, row, settings) == ""


def test_unresolvable_guild_mentions_best_effort() -> None:
    # When the guild isn't cached we can't verify; still emit the mention.
    row = SimpleNamespace(ping_role_id=111)
    settings = SimpleNamespace(default_ping_role_id=222)
    assert _compose_ping(None, row, settings) == "<@&111>"
