"""Measured (not configured) figures for the 📡 status channel: how often allies
and enemies really get re-checked, and how long after a death it gets posted."""

from __future__ import annotations

import time
from collections import deque
from statistics import mean
from typing import Callable

CHECK_WINDOW = 10 * 60      # seconds of fast-check gaps averaged
DEATH_WINDOW = 24 * 3600    # seconds of death delays averaged


class Stats:
    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self.started = clock()
        self._checks: deque[tuple[float, str, float]] = deque()  # (when, side, seconds since its last check)
        self._deaths: deque[tuple[float, str, float]] = deque()  # (when, side, seconds after the death)

    @staticmethod
    def _trim(rows: deque, horizon: float) -> None:
        while rows and rows[0][0] < horizon:
            rows.popleft()

    def record_check(self, side: str, gap: float) -> None:
        self._checks.append((self._clock(), side, gap))
        self._trim(self._checks, self._clock() - CHECK_WINDOW)

    def record_death(self, side: str, delay: float) -> None:
        self._deaths.append((self._clock(), side, max(0.0, delay)))
        self._trim(self._deaths, self._clock() - DEATH_WINDOW)

    def check_every(self, side: str) -> float | None:
        """Average seconds between two checks of the same character, last 10 minutes."""
        self._trim(self._checks, self._clock() - CHECK_WINDOW)
        gaps = [gap for _, s, gap in self._checks if s == side]
        return mean(gaps) if gaps else None

    def death_delay(self, side: str) -> tuple[float, int] | None:
        """(average seconds from death to post, deaths counted), last 24 hours."""
        self._trim(self._deaths, self._clock() - DEATH_WINDOW)
        delays = [d for _, s, d in self._deaths if s == side]
        return (mean(delays), len(delays)) if delays else None

    @property
    def uptime(self) -> float:
        return self._clock() - self.started
