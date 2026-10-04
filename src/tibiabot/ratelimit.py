"""How fast the bot may ask tibia.com for pages, found by watching how it answers.

tibia.com (behind Cloudflare) doesn't publish a limit, and it counts per IP, so
the bot shares one rate across everything it fetches. It starts at a safe rate
and climbs slowly while answers stay clean; the first sign of pushback (403,
429, or TibiaData failing upstream) halves it and pauses for a minute. Additive
increase, multiplicative decrease: it settles just under what tibia.com
tolerates instead of guessing a number.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

PUSHBACK_STATUSES = frozenset({403, 429, 502, 503})


class AdaptiveRate:
    def __init__(self, start: float, ceiling: float, floor: float = 0.25, step: float = 0.25,
                 quiet_seconds: float = 600, pause_seconds: float = 60,
                 clock: Callable[[], float] = time.monotonic):
        self.ceiling = max(ceiling, floor)
        self.floor = floor
        self.rate = min(max(start, floor), self.ceiling)
        self._step = step
        self._quiet = quiet_seconds
        self._pause = pause_seconds
        self._clock = clock
        self._last_change = clock()
        self._paused_until = 0.0
        self._next_slot = 0.0

    @property
    def paused(self) -> bool:
        return self._clock() < self._paused_until

    def on_pushback(self, status: int) -> None:
        """tibia.com (or TibiaData on its behalf) refused or failed: back off. A burst of
        errors during the pause that follows counts once."""
        if status not in PUSHBACK_STATUSES or self.paused:
            return
        before, now = self.rate, self._clock()
        self.rate = max(self.floor, self.rate / 2)
        self._paused_until = now + self._pause
        self._last_change = now
        log.warning("tibia.com pushed back (%s): fast checks %.2f -> %.2f/s, pausing %.0fs",
                    status, before, self.rate, self._pause)

    def _maybe_raise(self) -> None:
        now = self._clock()
        if self.rate < self.ceiling and now - self._last_change >= self._quiet:
            before = self.rate
            self.rate = min(self.ceiling, self.rate + self._step)
            self._last_change = now
            log.info("No pushback for %.0f min: fast checks %.2f -> %.2f/s", self._quiet / 60, before, self.rate)

    async def acquire(self, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        """Wait for this request's turn: requests are spaced 1/rate apart, and none go
        out during a pause."""
        self._maybe_raise()
        now = self._clock()
        slot = max(now, self._next_slot, self._paused_until)
        self._next_slot = slot + 1 / self.rate
        if slot > now:
            await sleep(slot - now)
