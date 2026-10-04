"""Daily kill statistics: fetched once per world after tibia.com publishes them,
kept for boss predictions and the daily statistics post.

tibia.com publishes the day's figures between about 03:00 and 03:20 Berlin; a
world counts as rolled over once its figures differ from the day before.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import asyncpg

from tibiabot import bosses
from tibiabot.serversave import BERLIN
from tibiabot.tibiadata.client import TibiaDataClient, TibiaDataError
from tibiabot.tibiadata.models import KillStatistics, KillStatisticsEntry

log = logging.getLogger(__name__)

NOT_CREATURES = {"players", "(elemental forces)"}
TOP_KILLS = 10
BOUNDARY_HOUR = 4          # after this, the day before is on the page
SETTLE = timedelta(hours=1)  # with nothing to compare against, trust the clock after this


def reported_day(at: datetime) -> date:
    """The day the kill-statistics page currently describes."""
    return ((at.astimezone(BERLIN) - timedelta(hours=BOUNDARY_HOUR)).date()) - timedelta(days=1)


def is_creature(race: str) -> bool:
    return race.lower() not in NOT_CREATURES


@dataclass(frozen=True)
class DaySummary:
    world: str
    day: date
    most_killed: tuple[str, int] | None
    deadliest: tuple[str, int] | None
    player_deaths: int
    total_killed: int
    total_players_killed: int

    @property
    def figures(self) -> tuple:
        return self.most_killed, self.deadliest, self.player_deaths, self.total_killed, self.total_players_killed


def top_killed(entries: list[KillStatisticsEntry], limit: int = TOP_KILLS) -> list[KillStatisticsEntry]:
    return sorted((e for e in entries if is_creature(e.race) and e.last_day_killed > 0),
                  key=lambda e: (-e.last_day_killed, e.race))[:limit]


def summary(data: KillStatistics, day: date) -> DaySummary:
    top = top_killed(data.entries, 1)
    deadly = sorted((e for e in data.entries if is_creature(e.race) and e.last_day_players_killed > 0),
                    key=lambda e: (-e.last_day_players_killed, e.race))
    players = next((e.last_day_players_killed for e in data.entries if e.race.lower() == "players"), 0)
    return DaySummary(data.world, day, (top[0].race, top[0].last_day_killed) if top else None,
                      (deadly[0].race, deadly[0].last_day_players_killed) if deadly else None, players,
                      sum(e.last_day_killed for e in data.entries),
                      sum(e.last_day_players_killed for e in data.entries))


def day_races(data: KillStatistics, day: date) -> list[tuple[str, int, int]]:
    """Every catalogued boss, zeroes included (a day looked at and empty is
    evidence too), then the day's most-killed creatures."""
    seen = {e.race.lower(): e for e in data.entries}
    rows: dict[str, tuple[str, int, int]] = {}
    for boss in bosses.catalogue():
        e = seen.get(boss.race.lower())
        rows[boss.race.lower()] = (boss.race, e.last_day_killed if e else 0, e.last_day_players_killed if e else 0)
    for e in top_killed(data.entries):
        rows.setdefault(e.race.lower(), (e.race, e.last_day_killed, e.last_day_players_killed))
    return list(rows.values())


class KillStatsStore:
    def __init__(self, cache: asyncpg.Pool):
        self.cache = cache

    async def has_day(self, world: str, day: date) -> bool:
        return bool(await self.cache.fetchval(
            "SELECT 1 FROM kill_statistics_summary WHERE world = $1 AND save_day = $2", world, day))

    async def summary(self, world: str, day: date) -> DaySummary | None:
        r = await self.cache.fetchrow("SELECT * FROM kill_statistics_summary WHERE world = $1 AND save_day = $2",
                                      world, day)
        if r is None:
            return None
        return DaySummary(world, day, (r["most_killed_race"], r["most_killed"]) if r["most_killed_race"] else None,
                          (r["deadliest_race"], r["deadliest_kills"]) if r["deadliest_race"] else None,
                          r["player_deaths"], r["total_killed"], r["total_players_killed"])

    async def file(self, data: KillStatistics, day: date) -> None:
        s = summary(data, day)
        async with self.cache.acquire() as conn, conn.transaction():
            await conn.executemany(
                "INSERT INTO kill_statistics_boss (world, save_day, race, killed, players_killed) "
                "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (world, save_day, race) DO UPDATE SET "
                "killed = EXCLUDED.killed, players_killed = EXCLUDED.players_killed",
                [(data.world, day, race, killed, pk) for race, killed, pk in day_races(data, day)])
            await conn.execute(
                "INSERT INTO kill_statistics_summary (world, save_day, most_killed_race, most_killed, deadliest_race, "
                "deadliest_kills, player_deaths, total_killed, total_players_killed) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) ON CONFLICT (world, save_day) DO UPDATE SET "
                "most_killed_race = EXCLUDED.most_killed_race, most_killed = EXCLUDED.most_killed, "
                "deadliest_race = EXCLUDED.deadliest_race, deadliest_kills = EXCLUDED.deadliest_kills, "
                "player_deaths = EXCLUDED.player_deaths, total_killed = EXCLUDED.total_killed, "
                "total_players_killed = EXCLUDED.total_players_killed",
                data.world, day, s.most_killed[0] if s.most_killed else "", s.most_killed[1] if s.most_killed else 0,
                s.deadliest[0] if s.deadliest else "", s.deadliest[1] if s.deadliest else 0, s.player_deaths,
                s.total_killed, s.total_players_killed)

    async def sightings(self, world: str) -> dict[str, list[tuple[date, int]]]:
        rows = await self.cache.fetch(
            "SELECT race, save_day, killed FROM kill_statistics_boss WHERE world = $1 "
            "AND (killed > 0 OR players_killed > 0) ORDER BY race ASC, save_day DESC", world)
        out: dict[str, list[tuple[date, int]]] = {}
        for r in rows:
            out.setdefault(r["race"].lower(), []).append((r["save_day"], r["killed"]))
        return out

    async def prune(self, keep_days: int = 400) -> None:
        cutoff = date.today() - timedelta(days=keep_days)
        await self.cache.execute("DELETE FROM kill_statistics_boss WHERE save_day < $1", cutoff)
        await self.cache.execute("DELETE FROM kill_statistics_summary WHERE save_day < $1", cutoff)


async def collect(client: TibiaDataClient, store: KillStatsStore, worlds: list[str],
                  now: datetime | None = None) -> list[str]:
    """File the reported day for every world that has rolled over. Returns the worlds filed."""
    now = now or datetime.now(timezone.utc)
    day = reported_day(now)
    berlin = now.astimezone(BERLIN)
    boundary = berlin.replace(hour=BOUNDARY_HOUR, minute=0, second=0, microsecond=0)
    if berlin < boundary:
        boundary -= timedelta(days=1)
    settled = berlin - boundary >= SETTLE
    filed = []
    for world in sorted(set(worlds)):
        if await store.has_day(world, day):
            continue
        try:
            data = await client.kill_statistics(world)
        except TibiaDataError as e:
            log.debug("Kill statistics for %s unavailable: %s", world, e)
            continue
        if not any(e.last_day_killed for e in data.entries):
            continue  # an empty page: tibia.com mid-update
        before = await store.summary(world, day - timedelta(days=1))
        if before is not None and before.figures == summary(data, day).figures:
            continue  # still the day before
        if before is None and not settled:
            continue  # nothing to compare with: wait until it must have rolled
        await store.file(data, day)
        filed.append(world)
    if filed:
        log.info("Kill statistics filed for %s: %s", day, ", ".join(filed))
    return filed
