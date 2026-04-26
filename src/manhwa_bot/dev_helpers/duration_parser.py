"""Re-export of :func:`parse_duration` so the dev cog imports from a stable path."""

from ..premium.grants import parse_duration

__all__ = ["parse_duration"]
