"""Bot entry point. The only Python file allowed at the repository root."""

from __future__ import annotations

import asyncio
import os
import sys


def _verify_package_path() -> None:
    """Refuse to start if manhwa_bot loads from a sibling worktree's src tree.

    Running this main.py with the wrong venv (one whose editable install
    points at a different copy of the package) loads two distinct
    ``manhwa_bot.crawler.errors.CrawlerError`` classes — one from cwd and
    one from the editable install — so ``except CrawlerError`` in cogs
    fails to catch errors raised by the client, and ``request_progress``
    events arrive at a client object that has no dispatch handler.
    """
    import manhwa_bot

    pkg_file = manhwa_bot.__file__
    if pkg_file is None:
        return
    pkg_dir = os.path.normpath(os.path.dirname(os.path.abspath(pkg_file)))
    this_dir = os.path.dirname(os.path.abspath(__file__))
    expected = os.path.normpath(os.path.join(this_dir, "src", "manhwa_bot"))
    if pkg_dir != expected:
        sys.exit(
            f"\nERROR: manhwa_bot is loading from {pkg_dir!r}, "
            f"but main.py is in {this_dir!r}.\n\n"
            f"Use this directory's own venv to run the bot:\n\n"
            f"    {os.path.join(this_dir, '.venv', 'Scripts', 'python.exe')} main.py\n\n"
            f"Running with a different repo's venv loads two copies of manhwa_bot "
            f"and silently breaks isinstance checks on exceptions plus the "
            f"WebSocket progress dispatch.\n"
        )


_verify_package_path()


from manhwa_bot.app import run  # noqa: E402


if __name__ == "__main__":
    asyncio.run(run())
