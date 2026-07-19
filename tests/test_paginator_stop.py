"""Regression coverage for removing paginator controls."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from manhwa_bot.ui.components.paginator import LayoutPaginator


def test_stop_disables_controls_without_clearing_the_layout_message() -> None:
    async def _run() -> None:
        page = MagicMock()
        button = SimpleNamespace(disabled=False)
        page.walk_children.return_value = [button]
        paginator = LayoutPaginator([page], invoker_id=None)
        interaction = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock(), edit_message=AsyncMock()),
        )

        await paginator.handle_nav(interaction, "stop")

        assert button.disabled is True
        interaction.response.edit_message.assert_awaited_once_with(view=page)
        page.stop.assert_called_once_with()

    asyncio.run(_run())
