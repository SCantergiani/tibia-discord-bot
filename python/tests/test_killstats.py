import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tibiabot import killstats
from tibiabot.config import Settings
from tibiabot.db.database import Database
from tibiabot.tibiadata.client import TibiaDataError
from tibiabot.tibiadata.models import KillStatistics, KillStatisticsEntry

FIXTURE = KillStatistics.from_json(json.loads((Path(__file__).parent / "fixtures/killstatistics.json").read_text()))


def test_reported_day_turns_over_at_four_in_berlin():
    # 01:59 UTC = 03:59 Berlin (CEST): still two days back; 02:00 UTC = 04:00: yesterday.
    assert killstats.reported_day(datetime(2026, 10, 4, 1, 59, tzinfo=timezone.utc)) == date(2026, 10, 2)
    assert killstats.reported_day(datetime(2026, 10, 4, 2, 0, tzinfo=timezone.utc)) == date(2026, 10, 3)


def test_summary_ignores_players_and_elemental_forces_as_creatures():
    s = killstats.summary(FIXTURE, date(2026, 10, 3))
    assert s.most_killed and s.most_killed[0].lower() not in killstats.NOT_CREATURES
    assert s.total_killed == sum(e.last_day_killed for e in FIXTURE.entries)


def test_day_races_include_every_catalogued_boss_even_unseen():
    from tibiabot import bosses
    races = {r[0].lower() for r in killstats.day_races(FIXTURE, date(2026, 10, 3))}
    assert {b.race.lower() for b in bosses.catalogue()} <= races


# --- collection against a real database -------------------------------------

pg = pytest.mark.skipif(not (os.getenv("POSTGRES_HOST") and os.getenv("POSTGRES_PASSWORD")),
                        reason="needs a Postgres (POSTGRES_HOST, POSTGRES_PASSWORD)")
WORLD = "Statworld"


def page(ferumbras_kills: int, rats: int) -> KillStatistics:
    return KillStatistics(WORLD, [KillStatisticsEntry("Ferumbras", ferumbras_kills, 0, ferumbras_kills, 0),
                                  KillStatisticsEntry("rats", rats, 0, rats, 0),
                                  KillStatisticsEntry("players", 0, 12, 0, 80)])


class FakeClient:
    def __init__(self, data):
        self.data = data

    async def kill_statistics(self, world):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


@pytest.fixture
async def store():
    db = Database(Settings(token="x", postgres_host=os.environ["POSTGRES_HOST"],
                           postgres_password=os.environ["POSTGRES_PASSWORD"],
                           postgres_port=int(os.getenv("POSTGRES_PORT", "5432"))))
    await db.start()
    for table in ("kill_statistics_boss", "kill_statistics_summary"):
        await db.cache.execute(f"DELETE FROM {table} WHERE world = $1", WORLD)
    yield killstats.KillStatsStore(db.cache)
    for table in ("kill_statistics_boss", "kill_statistics_summary"):
        await db.cache.execute(f"DELETE FROM {table} WHERE world = $1", WORLD)
    await db.close()


EARLY = datetime(2026, 10, 4, 2, 30, tzinfo=timezone.utc)   # 04:30 Berlin
LATE = datetime(2026, 10, 4, 3, 30, tzinfo=timezone.utc)    # 05:30 Berlin, settled


@pg
async def test_first_ever_day_waits_for_the_settle_time(store):
    assert await killstats.collect(FakeClient(page(1, 500)), store, [WORLD], EARLY) == []
    assert await killstats.collect(FakeClient(page(1, 500)), store, [WORLD], LATE) == [WORLD]
    assert (await store.sightings(WORLD))["ferumbras"] == [(date(2026, 10, 3), 1)]


@pg
async def test_a_page_identical_to_yesterday_has_not_rolled_over(store):
    await store.file(page(0, 500), date(2026, 10, 2))
    assert await killstats.collect(FakeClient(page(0, 500)), store, [WORLD], LATE) == []
    assert await killstats.collect(FakeClient(page(0, 600)), store, [WORLD], EARLY) == [WORLD]


@pg
async def test_each_day_is_filed_once_and_failures_are_retried(store):
    assert await killstats.collect(FakeClient(TibiaDataError("down")), store, [WORLD], LATE) == []
    assert await killstats.collect(FakeClient(page(0, 500)), store, [WORLD], LATE) == [WORLD]
    assert await killstats.collect(FakeClient(page(0, 999)), store, [WORLD], LATE) == []


@pg
async def test_creature_kills_exclude_bosses(store):
    await store.file(page(2, 500), date(2026, 10, 3))
    assert await store.kills_on(WORLD, date(2026, 10, 3)) == [("rats", 500)]
