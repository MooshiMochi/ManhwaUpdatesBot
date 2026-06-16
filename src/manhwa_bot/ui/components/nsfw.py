"""NSFW cover spoiler-policy resolution.

The crawler classifies covers and sends ``is_nsfw`` in series payloads. The bot
decides whether to spoiler a flagged cover based on a per-guild / per-user mode:

- ``always``             — spoiler every NSFW cover everywhere (default; safest).
- ``never``              — never spoiler.
- ``nsfw_channel_aware`` — show unspoilered only in age-gated NSFW channels.

The resolver is a pure function; callers pick which mode applies (guild mode in
guild channels, user mode in DMs) and pass the channel's NSFW flag.
"""

from __future__ import annotations

SPOILER_MODES: tuple[str, ...] = ("always", "never", "nsfw_channel_aware")
DEFAULT_SPOILER_MODE = "always"


def normalize_mode(mode: str | None) -> str:
    candidate = (mode or "").strip().lower()
    return candidate if candidate in SPOILER_MODES else DEFAULT_SPOILER_MODE


def should_spoiler(
    is_nsfw: bool | None,
    *,
    mode: str | None = DEFAULT_SPOILER_MODE,
    channel_is_nsfw: bool = False,
) -> bool:
    """Return whether a cover should be rendered as a spoiler."""
    if not is_nsfw:
        return False
    resolved = normalize_mode(mode)
    if resolved == "never":
        return False
    if resolved == "nsfw_channel_aware":
        return not channel_is_nsfw
    return True  # "always"
