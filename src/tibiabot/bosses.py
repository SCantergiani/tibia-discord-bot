"""Rare boss spawn predictions from kill-statistics sightings.

Ported from BossCatalogue/BossPredictor.scala, which follow kik-tibia's
boss-tracker: a boss respawns somewhere between `window_min` and `window_max`
days after it was last killed, and a narrow window repeats (tiles) until a
later kill resets it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from importlib import resources

from tibiabot.serversave import BERLIN, SERVER_SAVE

HIGH, LOW, NONE = 2, 1, 0


@dataclass(frozen=True)
class Boss:
    name: str
    race_name: str | None
    predict: bool
    window_min: int
    window_max: int
    spawn_points: int
    category: str

    @property
    def race(self) -> str:
        """How the boss appears in kill statistics."""
        return self.race_name or self.name


@lru_cache(maxsize=1)
def catalogue() -> tuple[Boss, ...]:
    raw = json.loads(resources.files("tibiabot.data").joinpath("bosses.json").read_text(encoding="utf-8"))
    return tuple(Boss(name=b["name"].strip(), race_name=(b.get("raceName") or "").strip() or None,
                      predict=b.get("predict", True), window_min=int(b["windowMin"]), window_max=int(b["windowMax"]),
                      spawn_points=int(b.get("spawnPoints", 1)), category=(b.get("category") or "").strip())
                 for b in raw["bosses"])


def _tdiv(a: int, b: int) -> int:
    """Integer division rounding towards zero, like the JVM's."""
    q = abs(a) // b
    return q if a >= 0 else -q


def save_on(day: date) -> datetime:
    return datetime.combine(day, SERVER_SAVE, tzinfo=BERLIN)


@dataclass(frozen=True)
class BossChance:
    chance: int
    days_since: int
    window_min: int
    window_max: int | None
    last_seen: date

    @property
    def opens_at(self) -> datetime:
        return save_on(self.last_seen + timedelta(days=self.window_min))

    @property
    def closes_at(self) -> datetime | None:
        return save_on(self.last_seen + timedelta(days=self.window_max)) if self.window_max is not None else None


@dataclass(frozen=True)
class BossPrediction:
    boss: Boss
    chances: list[BossChance] = field(default_factory=list)

    @property
    def best(self) -> int:
        return max((c.chance for c in self.chances), default=NONE)

    @property
    def leading(self) -> list[BossChance]:
        return [c for c in self.chances if c.chance == self.best]

    @property
    def days_since(self) -> int:
        return min((c.days_since for c in self.chances), default=0)


def chance_for(today: date, last_seen: date, lo: int, hi: int) -> BossChance:
    days = max(0, (today - last_seen).days)
    start_high = _tdiv(days, max(1, lo))
    end_high = _tdiv(days - 1, max(1, hi)) + 1
    start_low = _tdiv(days, max(1, lo - 1))
    end_low = _tdiv(days - 1, max(1, hi + 1)) + 1
    chance = HIGH if start_high >= end_high else LOW if start_low >= end_low else NONE
    if days <= hi:
        return BossChance(chance, days, lo, hi, last_seen)
    start_of_endless = _tdiv(hi - 1, max(1, hi - lo)) * lo
    window_start = min(max(start_high, 1) * lo, start_of_endless)
    window_end = max(start_high, 1) * hi
    return BossChance(chance, days, window_start, None if window_start >= start_of_endless else window_end, last_seen)


def predict(boss: Boss, sightings: list[tuple[date, int]], today: date) -> BossPrediction | None:
    """`sightings`: (day, killed) newest first."""
    if not boss.predict or not sightings:
        return None
    if boss.spawn_points <= 1:
        days = [sightings[0][0]]
    else:
        days = [d for d, killed in sightings for _ in range(max(1, killed))][:boss.spawn_points]
    return BossPrediction(boss, [chance_for(today, d, boss.window_min, boss.window_max) for d in days])


def predict_all(sightings: dict[str, list[tuple[date, int]]], today: date) -> list[BossPrediction]:
    found = [p for b in catalogue() if (p := predict(b, sightings.get(b.race.lower(), []), today))]
    return sorted(found, key=lambda p: (-p.best, -p.days_since, p.boss.name))


def awaiting_first_sighting(sightings: dict[str, list[tuple[date, int]]]) -> int:
    return sum(1 for b in catalogue() if b.predict and not sightings.get(b.race.lower()))
