"""Sanity test: ensure manhwa_bot loads from exactly one source tree.

This catches the dual-namespace footgun where running ``main.py`` from a
worktree with the wrong venv would import some modules from MAIN src and
others from WORKTREE src, breaking ``except CrawlerError`` clauses.
"""

from __future__ import annotations

import importlib
import sys


def test_manhwa_bot_loads_once() -> None:
    pkg = importlib.import_module("manhwa_bot")
    errors_mod = importlib.import_module("manhwa_bot.crawler.errors")
    assert errors_mod.__name__ == "manhwa_bot.crawler.errors"
    assert errors_mod.__file__ is not None
    assert errors_mod.__file__.startswith(pkg.__path__[0])


def test_no_src_manhwa_bot_modules_loaded() -> None:
    leaked = [name for name in sys.modules if name.startswith("src.manhwa_bot")]
    assert leaked == [], f"src.manhwa_bot modules leaked into sys.modules: {leaked}"
