"""One polling loop per tracked world, shared by every guild tracking it.

Each tick fetches the world's online list, then the character sheet of everyone
online plus anyone seen online in the last 10 minutes (a death logs you out, so
the sheet that shows it is fetched after the name has left the list). The result
is handed to every listener; deaths, levels and online lists are listeners.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from tibiabot.tibiadata.age_cache import CharacterAgeCache
from tibiabot.tibiadata.client import NotFound, TibiaDataClient, TibiaDataError
from tibiabot.tibiadata.models import Character, OnlinePlayer

log = logging.getLogger(__name__)

RECENTLY_OFFLINE_SECONDS = 600
SHEET_CONCURRENCY = 32


@dataclass
class WorldSnapshot:
    world: str
    taken_at: float
    online: list[OnlinePlayer]
    characters: dict[str, Character] = field(default_factory=dict)
    recently_offline: list[str] = field(default_factory=list)
    first_tick: bool = False
    # A fast-lane snapshot: fresh sheets for a few allies/enemies only, with the
    # online list from the last full poll. Online lists must ignore these.
    partial: bool = False


Listener = Callable[[WorldSnapshot], Awaitable[None]]
# (world, character name, last known sheet or None) -> re-fetch on every tick?
Priority = Callable[[str, str, "Character | None"], bool]
# world -> does any server tracking it want players who aren't allies or enemies?
WantsNeutrals = Callable[[str], bool]


@dataclass(frozen=True)
class FastLane:
    """Re-check prioritised characters' sheets between full polls.

    tibia.com refreshes its online list about once a minute but serves a character
    page fresh, and a death shows there (and logs the character out) at once. So
    between full polls, only allies and enemies are re-fetched, at most
    `max_per_second` of them, rotating when there are more than one interval's
    budget. Anyone who just logged out goes first: dying logs you out."""
    interval: float = 5
    max_per_second: float = 2

    @property
    def budget(self) -> int:
        return max(1, int(self.interval * self.max_per_second))


class WorldPoller:
    def __init__(self, world: str, client: TibiaDataClient, sheets: CharacterAgeCache,
                 listeners: list[Listener], interval: float = 60, priority: Priority | None = None,
                 fast_lane: FastLane | None = None, relevant: Priority | None = None,
                 wants_neutrals: WantsNeutrals | None = None):
        self.world = world
        self._priority = priority
        self._relevant = relevant
        self._wants_neutrals = wants_neutrals
        self._fast = fast_lane if priority else None
        self._online: list[OnlinePlayer] = []
        self._rotation = 0
        self._fast_task: asyncio.Task | None = None
        self._listen_lock = asyncio.Lock()
        self._client = client
        self._sheets = sheets
        self._listeners = listeners
        self._interval = interval
        self._last_seen: dict[str, float] = {}
        self._ticks = 0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"poll:{self.world}")
        if self._fast and self._fast_task is None:
            self._fast_task = asyncio.create_task(self._run_fast(), name=f"fast:{self.world}")

    async def stop(self) -> None:
        for task in (self._task, self._fast_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = self._fast_task = None

    async def _run(self) -> None:
        # Spread worlds across the minute so they don't all hit TibiaData at once.
        await asyncio.sleep(2 + random.uniform(0, self._interval))
        while True:
            started = time.monotonic()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Poll of %s failed", self.world)
            await asyncio.sleep(max(1.0, self._interval - (time.monotonic() - started)))

    async def _run_fast(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await self.fast_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Fast poll of %s failed", self.world)
            await asyncio.sleep(max(0.5, self._fast.interval - (time.monotonic() - started)))

    def fast_candidates(self) -> list[str]:
        """This round's prioritised names: the most recently logged out first, then
        a rotating slice of those online, within the per-interval budget."""
        peek = self._sheets.peek
        offline = sorted((n for n in set(self._last_seen) - {p.name for p in self._online}
                          if self._priority(self.world, n, peek(n))),
                         key=lambda n: -self._last_seen[n])
        online = [p.name for p in self._online if self._priority(self.world, p.name, peek(p.name))]
        picked = offline[:self._fast.budget]
        room = self._fast.budget - len(picked)
        if room > 0 and online:
            start = self._rotation % len(online)
            picked += (online[start:] + online[:start])[:room]
            self._rotation = start + room
        return picked

    async def fast_tick(self) -> WorldSnapshot | None:
        if self._ticks == 0:
            return None  # nothing known about who is online yet
        names = self.fast_candidates()
        if not names:
            return None
        snapshot = WorldSnapshot(self.world, time.time(), self._online, partial=True,
                                 characters=await self._fetch_sheets(names, fresh=True))
        await self._notify(snapshot)
        return snapshot

    async def _notify(self, snapshot: WorldSnapshot) -> None:
        async with self._listen_lock:
            for listener in self._listeners:
                try:
                    await listener(snapshot)
                except Exception:
                    log.exception("Listener failed on %s", self.world)

    async def tick(self) -> WorldSnapshot | None:
        try:
            world = await self._client.world(self.world)
        except TibiaDataError as e:
            log.warning("World %s unavailable this tick: %s", self.world, e)
            return None
        now = time.time()
        online_names = {p.name for p in world.online_players}
        for name in online_names:
            self._last_seen[name] = now
        self._last_seen = {n: t for n, t in self._last_seen.items() if now - t <= RECENTLY_OFFLINE_SECONDS}
        recently_offline = sorted(set(self._last_seen) - online_names)
        self._online = world.online_players

        snapshot = WorldSnapshot(self.world, now, world.online_players,
                                 recently_offline=recently_offline, first_tick=self._ticks == 0)
        names = [*online_names, *recently_offline]
        if self._relevant and self._wants_neutrals and not self._wants_neutrals(self.world):
            # Nobody wants neutral deaths or levels here: skip their sheets entirely.
            names = [n for n in names if self._relevant(self.world, n, self._sheets.peek(n))]
        snapshot.characters = await self._fetch_sheets(names)
        self._ticks += 1
        log.debug("%s: %d online, %d sheets", self.world, len(online_names), len(snapshot.characters))
        await self._notify(snapshot)
        return snapshot

    async def _fetch_sheets(self, names: list[str], fresh: bool = False) -> dict[str, Character]:
        gate = asyncio.Semaphore(SHEET_CONCURRENCY)
        result: dict[str, Character] = {}

        async def one(name: str) -> None:
            async with gate:
                # With a fast lane, prioritised sheets are already kept fresh by it.
                again = fresh or (bool(self._priority) and not self._fast
                                  and self._priority(self.world, name, self._sheets.peek(name)))
                try:
                    result[name] = await self._sheets.get(name, fresh=again)
                except NotFound:
                    self._last_seen.pop(name, None)
                except TibiaDataError as e:
                    log.debug("Sheet for %s unavailable: %s", name, e)

        await asyncio.gather(*(one(n) for n in names))
        return result


class PollerRegistry:
    """Starts a poller when the first guild tracks a world, stops it with the last."""

    def __init__(self, client: TibiaDataClient, sheets: CharacterAgeCache, interval: float = 60,
                 priority: Priority | None = None, fast_lane: FastLane | None = None,
                 relevant: Priority | None = None, wants_neutrals: WantsNeutrals | None = None):
        self._client = client
        self._priority = priority
        self._fast = fast_lane
        self._relevant = relevant
        self._wants_neutrals = wants_neutrals
        self._sheets = sheets
        self._interval = interval
        self._pollers: dict[str, WorldPoller] = {}
        self.listeners: list[Listener] = []

    @property
    def worlds(self) -> set[str]:
        return set(self._pollers)

    async def sync(self, wanted: set[str]) -> None:
        for world in set(self._pollers) - wanted:
            await self._pollers.pop(world).stop()
            log.info("Stopped polling %s", world)
        for world in wanted - set(self._pollers):
            poller = WorldPoller(world, self._client, self._sheets, self.listeners, self._interval, self._priority,
                                 self._fast, self._relevant, self._wants_neutrals)
            self._pollers[world] = poller
            poller.start()
            log.info("Started polling %s", world)

    async def stop_all(self) -> None:
        await self.sync(set())
