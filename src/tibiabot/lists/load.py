"""What tracking a set of characters costs: how often each online enemy and ally
gets its fast check, and the outbound traffic that implies.

Enemies are served first, every `enemy_every` seconds; allies every
`ally_every` with whatever the rate cap leaves. Measured on a live world: each
tibia.com page fetched costs ~1.4 KB of outbound traffic (pages are ~50 KB even
compressed; receiving them is acknowledged), so one request per second for a
month is about 3.6 GB.
"""

from __future__ import annotations

from dataclasses import dataclass

GB_PER_MONTH_PER_REQUEST_PER_SECOND = 3.6


@dataclass(frozen=True)
class Load:
    tracked: int
    enemies_online: int
    allies_online: int
    enemy_every: float | None   # seconds between an online enemy's checks; None: fast checks off
    ally_every: float | None    # same for allies; None also when enemies use the whole rate
    gb_per_month: float | None  # at this many online all month

    @property
    def online(self) -> int:
        return self.enemies_online + self.allies_online

    def text(self) -> str:
        base = (f"Tracking {self.tracked} characters · {self.enemies_online} enemies and "
                f"{self.allies_online} allies online")
        if self.enemy_every is None:
            return base
        allies = f"allies every ~{self.ally_every:.0f}s" if self.ally_every else "allies wait for the enemies"
        return (f"{base} · enemies checked every ~{self.enemy_every:.0f}s, {allies} · "
                f"~{self.gb_per_month:.1f} GB/month at this rate")


def estimate(tracked: int, enemies: int, allies: int, enemy_every: float | None, ally_every: float | None,
             cap: float | None) -> Load:
    if not enemy_every or not ally_every or not cap:
        return Load(tracked, enemies, allies, None, None, None)
    enemy_demand = enemies / enemy_every
    if enemy_demand >= cap:
        return Load(tracked, enemies, allies, enemies / cap, None if allies else ally_every,
                    cap * GB_PER_MONTH_PER_REQUEST_PER_SECOND)
    left = cap - enemy_demand
    ally_demand = allies / ally_every
    ally_check = ally_every if ally_demand <= left else allies / left
    rate = enemy_demand + min(ally_demand, left)
    return Load(tracked, enemies, allies, enemy_every, ally_check, rate * GB_PER_MONTH_PER_REQUEST_PER_SECOND)
