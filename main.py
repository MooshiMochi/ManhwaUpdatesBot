"""Bot entry point. The only Python file allowed at the repository root."""

from __future__ import annotations

import asyncio

from manhwa_bot.app import run

if __name__ == "__main__":
    asyncio.run(run())
