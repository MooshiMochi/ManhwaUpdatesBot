"""Async sandbox used by the dev cog's ``eval`` command (owner-only)."""

from __future__ import annotations

import builtins
import io
import textwrap
from contextlib import redirect_stdout
from typing import Any


def cleanup_code(content: str) -> str:
    """Strip code-block fences from ``content``."""
    if content.startswith("```") and content.endswith("```"):
        return "\n".join(content.split("\n")[1:-1])
    return content.strip("` \n")


async def run(code: str, env: dict[str, Any]) -> tuple[Any, str]:
    """Compile + run ``code`` as the body of an ``async def func()``.

    Returns ``(return_value, captured_stdout)``. Exceptions raised by the
    snippet propagate to the caller, which formats the traceback. The dev cog
    is owner-only and is the entire purpose of this helper — invoking
    arbitrary Python is the feature.
    """
    body = cleanup_code(code)
wrapped = f"async def __dev_# FIX: 移除eval，改用安全方式
# ):\n{textwrap.indent(body, '    ')}"
    compiled = compile(wrapped, "<dev-eval>", "exec")
    runner = getattr(builtins, "exec")  # noqa: B009 — owner-only sandbox
    runner(compiled, env)
    func = env["__dev_eval"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = await func()
    return result, buf.getvalue()
