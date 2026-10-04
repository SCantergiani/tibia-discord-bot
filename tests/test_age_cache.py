from dataclasses import replace
from datetime import datetime, timezone

import pytest

from tibiabot.tibiadata.age_cache import CharacterAgeCache
from tibiabot.tibiadata.client import TibiaDataError
from tibiabot.tibiadata.models import Character

T0 = 1_000_000.0


def sheet(origin: float | None) -> Character:
    stamp = datetime.fromtimestamp(origin, timezone.utc) if origin is not None else None
    return Character(name="Bubble", level=100, vocation="Elite Knight", world="Antica", sex="male",
                     guild_name=None, guild_rank=None, former_names=[], former_worlds=[], last_login=None,
                     account_status="", traded=False, deletion_date=None, comment="", origin_timestamp=stamp)


class FakeUpstream:
    def __init__(self):
        self.calls = 0
        self.next: Character | Exception = sheet(T0)

    async def __call__(self, name: str) -> Character:
        self.calls += 1
        if isinstance(self.next, Exception):
            raise self.next
        return self.next


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def upstream():
    return FakeUpstream()


@pytest.fixture
def clock():
    return Clock()


async def test_reuses_sheet_until_upstream_copy_expires(upstream, clock):
    cache = CharacterAgeCache(upstream, ttl=300, clock=clock)
    await cache.get("Bubble")
    clock.now = T0 + 299
    await cache.get("bubble")
    assert upstream.calls == 1


async def test_refetches_once_upstream_copy_has_expired(upstream, clock):
    cache = CharacterAgeCache(upstream, ttl=300, clock=clock)
    await cache.get("Bubble")
    clock.now = T0 + 300
    await cache.get("Bubble")
    assert upstream.calls == 2


async def test_an_old_upstream_copy_is_fresh_only_for_its_remaining_life(upstream, clock):
    upstream.next = sheet(T0 - 250)
    cache = CharacterAgeCache(upstream, ttl=300, clock=clock)
    await cache.get("Bubble")
    clock.now = T0 + 51
    await cache.get("Bubble")
    assert upstream.calls == 2


async def test_missing_origin_counts_from_fetch_time(upstream, clock):
    upstream.next = sheet(None)
    cache = CharacterAgeCache(upstream, ttl=300, clock=clock)
    await cache.get("Bubble")
    clock.now = T0 + 299
    await cache.get("Bubble")
    assert upstream.calls == 1


async def test_failure_is_covered_by_a_stored_sheet_within_max_stale(upstream, clock):
    cache = CharacterAgeCache(upstream, ttl=300, max_stale=900, clock=clock)
    first = await cache.get("Bubble")
    clock.now = T0 + 600
    upstream.next = TibiaDataError("down")
    assert await cache.get("Bubble") is first


async def test_failure_past_max_stale_is_raised(upstream, clock):
    cache = CharacterAgeCache(upstream, ttl=300, max_stale=900, clock=clock)
    await cache.get("Bubble")
    clock.now = T0 + 901
    upstream.next = TibiaDataError("down")
    with pytest.raises(TibiaDataError):
        await cache.get("Bubble")


async def test_oldest_entry_is_evicted_past_max_entries(upstream, clock):
    cache = CharacterAgeCache(upstream, ttl=300, max_entries=2, clock=clock)
    for name in ("A", "B", "C"):
        upstream.next = replace(sheet(T0), name=name)
        await cache.get(name)
    assert len(cache) == 2
    assert cache.peek("A") is None


async def test_fresh_gets_use_the_fresh_source_and_others_the_bulk_one():
    bulk, own = FakeUpstream(), FakeUpstream()
    cache = CharacterAgeCache(bulk, ttl=300, clock=lambda: T0 + 10, fetch_fresh=own)
    await cache.get("Bubble", fresh=True)
    assert (own.calls, bulk.calls) == (1, 0)
    cache.forget("Bubble")
    await cache.get("Bubble")
    assert (own.calls, bulk.calls) == (1, 1)


async def test_an_older_sheet_never_replaces_a_newer_one():
    now = [T0]
    bulk, own = FakeUpstream(), FakeUpstream()
    cache = CharacterAgeCache(bulk, ttl=300, clock=lambda: now[0], fetch_fresh=own)
    own.next = replace(sheet(T0), level=101)
    await cache.get("Bubble", fresh=True)
    now[0] = T0 + 300                                # our fresh copy has expired
    bulk.next = replace(sheet(T0 - 20), level=100)  # the public API still serves an older one
    assert (await cache.get("Bubble")).level == 101
    bulk.next = replace(sheet(T0 + 290), level=102)  # its next copy is newer: taken
    now[0] = T0 + 301
    assert (await cache.get("Bubble")).level == 102
