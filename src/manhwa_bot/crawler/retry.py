"""Reconnect backoff policy."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Backoff:
    initial: float
    maximum: float
    jitter: float
    factor: float = 2.0
    _current: float = 0.0

    def __post_init__(self) -> None:
        self._current = self.initial

    def reset(self) -> None:
        self._current = self.initial

    def next_delay(self) -> float:
        """Return the next sleep duration (seconds) and advance the schedule."""
        delay = min(self._current, self.maximum)
        jitter = random.uniform(0.0, self.jitter) if self.jitter > 0 else 0.0
        self._current = min(self._current * self.factor, self.maximum)
        return delay + jitter
