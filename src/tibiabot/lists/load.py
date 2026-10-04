"""What tracking a set of characters costs: how often each online ally/enemy gets
its fast check, and the outbound traffic that implies.

Measured on a live world: each tibia.com page fetched costs ~1.4 KB of outbound
traffic (pages are ~50 KB even compressed; receiving them is acknowledged), so
one request per second for a month is about 3.6 GB.
"""

from __future__ import annotations

from dataclasses import dataclass

GB_PER_MONTH_PER_REQUEST_PER_SECOND = 3.6


@dataclass(frozen=True)
class Load:
    tracked: int
    online: int
    check_every: float | None   # seconds between an online ally/enemy's checks; None: fast checks off
    gb_per_month: float | None  # at this many online all month; None: fast checks off

    def text(self) -> str:
        base = f"Tracking {self.tracked} characters · {self.online} online now"
        if self.check_every is None:
            return base
        return (f"{base} · each checked every ~{self.check_every:.0f}s · "
                f"~{self.gb_per_month:.1f} GB/month at this rate")


def estimate(tracked: int, online: int, interval: float | None, cap: float | None) -> Load:
    """`interval`/`cap`: the fast lane's FAST_POLL_SECONDS and FAST_POLL_MAX_PER_SECOND,
    None when there is no fast lane (public TibiaData)."""
    if not interval or not cap:
        return Load(tracked, online, None, None)
    rate = min(online / interval, cap)
    every = max(interval, online / cap) if online else interval
    return Load(tracked, online, every, rate * GB_PER_MONTH_PER_REQUEST_PER_SECOND)
