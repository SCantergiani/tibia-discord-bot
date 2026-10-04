"""Death and level detection against a real Postgres; skipped without one."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from tibiabot.config import Settings
from tibiabot.db.database import Database
from tibiabot.deaths import DeathDetector, LevelDetector
from tibiabot.poller import WorldSnapshot
from tibiabot.tibiadata.models import Character, Death, Killer, OnlinePlayer

pytestmark = pytest.mark.skipif(not (os.getenv("POSTGRES_HOST") and os.getenv("POSTGRES_PASSWORD")),
                                reason="needs a Postgres (POSTGRES_HOST, POSTGRES_PASSWORD)")

NOW = datetime.now(timezone.utc)
WORLD = "Testworld"


def sheet(name, level=100, deaths=(), last_login=NOW - timedelta(hours=1)):
    return Character(name=name, level=level, vocation="Knight", world=WORLD, sex="male", guild_name=None,
                     guild_rank=None, former_names=[], former_worlds=[], last_login=last_login, account_status="",
                     traded=False, deletion_date=None, comment="", deaths=list(deaths))


def death(minutes_ago, level=100):
    return Death(NOW - timedelta(minutes=minutes_ago), level, [Killer("rat", False, False, "")], [], "")


def snapshot(characters, online=()):
    return WorldSnapshot(WORLD, 0, list(online), characters={c.name: c for c in characters})


@pytest.fixture
async def cache():
    db = Database(Settings(token="x", postgres_host=os.environ["POSTGRES_HOST"],
                           postgres_password=os.environ["POSTGRES_PASSWORD"],
                           postgres_port=int(os.getenv("POSTGRES_PORT", "5432"))))
    await db.start()
    await db.cache.execute("DELETE FROM deaths WHERE world = $1", WORLD)
    await db.cache.execute("DELETE FROM levels WHERE world = $1", WORLD)
    yield db.cache
    await db.cache.execute("DELETE FROM deaths WHERE world = $1", WORLD)
    await db.cache.execute("DELETE FROM levels WHERE world = $1", WORLD)
    await db.close()


async def test_a_recent_death_is_reported_once(cache):
    detector = DeathDetector(cache)
    snap = snapshot([sheet("Bubble", deaths=[death(5)])])
    assert len(await detector.detect(snap, NOW)) == 1
    assert await detector.detect(snap, NOW) == []


async def test_old_deaths_are_ignored(cache):
    assert await DeathDetector(cache).detect(snapshot([sheet("Bubble", deaths=[death(31)])]), NOW) == []


async def test_a_restart_does_not_repost(cache):
    snap = snapshot([sheet("Bubble", deaths=[death(5)])])
    await DeathDetector(cache).detect(snap, NOW)
    assert await DeathDetector(cache).detect(snap, NOW) == []


async def test_level_up_is_online_level_above_sheet(cache):
    detector = LevelDetector(cache)
    snap = snapshot([sheet("Bubble", level=100)], [OnlinePlayer("Bubble", 101, "Knight")])
    ups = await detector.detect(snap, NOW)
    assert [(u.character.name, u.level) for u in ups] == [("Bubble", 101)]
    assert await detector.detect(snap, NOW) == []
    assert await LevelDetector(cache).detect(snap, NOW) == []  # survives a restart


async def test_no_level_up_right_after_a_death(cache):
    snap = snapshot([sheet("Bubble", level=100, deaths=[death(3)])], [OnlinePlayer("Bubble", 101, "Knight")])
    assert await LevelDetector(cache).detect(snap, NOW) == []


async def test_same_level_again_after_a_new_login_is_posted(cache):
    detector = LevelDetector(cache)
    online = [OnlinePlayer("Bubble", 101, "Knight")]
    await detector.detect(snapshot([sheet("Bubble", level=100)], online), NOW)
    relogged = snapshot([sheet("Bubble", level=100, last_login=NOW - timedelta(minutes=1))], online)
    assert len(await detector.detect(relogged, NOW)) == 1
