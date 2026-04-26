"""Async subprocess wrapper used by the dev cog's ``shell``/``pull`` commands.

Owner-only — accessible only via the dev cog's ``cog_check`` (commands.is_owner).
"""

from __future__ import annotations

import asyncio
from asyncio import subprocess as _asp


async def run(
    command: str | list[str],
    *,
    cwd: str | None = None,
    timeout: float = 60.0,
) -> tuple[str, str, int]:
    """Run ``command`` asynchronously and return decoded ``(stdout, stderr, rc)``.

    A ``list[str]`` argv launches the program directly without a shell. A
    ``str`` form launches via the user's shell for cases where the owner
    needs pipes or redirects. Both paths are owner-only via the dev cog
    cog-check.
    """
    if isinstance(command, list):
        launcher = _asp.create_subprocess_exec
        proc = await launcher(
            *command,
            stdout=_asp.PIPE,
            stderr=_asp.PIPE,
            cwd=cwd,
        )
    else:
        launcher = _asp.create_subprocess_shell
        proc = await launcher(
            command,
            stdout=_asp.PIPE,
            stderr=_asp.PIPE,
            cwd=cwd,
        )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return (
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
        proc.returncode if proc.returncode is not None else -1,
    )
