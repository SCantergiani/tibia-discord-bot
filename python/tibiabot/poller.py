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


Listener = Callable[[WorldSnapshot], Awaitable[None]]
# (world, character name, last known sheet or None) -> re-fetch on every tick?
Priority = Callable[[str, str, "Character | None"], bool]


class WorldPoller:
    def __init__(self, world: str, client: TibiaDataClient, sheets: CharacterAgeCache,
                 listeners: list[Listener], interval: float = 60, priority: Priority | None = None):
        self.world = world
        self._priority = priority
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

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

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

        snapshot = WorldSnapshot(self.world, now, world.online_players,
                                 recently_offline=recently_offline, first_tick=self._ticks == 0)
        snapshot.characters = await self._fetch_sheets([*online_names, *recently_offline])
        self._ticks += 1
        log.debug("%s: %d online, %d sheets", self.world, len(online_names), len(snapshot.characters))
        for listener in self._listeners:
            try:
                await listener(snapshot)
            except Exception:
                log.exception("Listener failed on %s", self.world)
        return snapshot

    async def _fetch_sheets(self, names: list[str]) -> dict[str, Character]:
        gate = asyncio.Semaphore(SHEET_CONCURRENCY)
        result: dict[str, Character] = {}

        async def one(name: str) -> None:
            async with gate:
                fresh = bool(self._priority) and self._priority(self.world, name, self._sheets.peek(name))
                try:
                    result[name] = await self._sheets.get(name, fresh=fresh)
                except NotFound:
                    self._last_seen.pop(name, None)
                except TibiaDataError as e:
                    log.debug("Sheet for %s unavailable: %s", name, e)

        await asyncio.gather(*(one(n) for n in names))
        return result


class PollerRegistry:
    """Starts a poller when the first guild tracks a world, stops it with the last."""

    def __init__(self, client: TibiaDataClient, sheets: CharacterAgeCache, interval: float = 60,
                 priority: Priority | None = None):
        self._client = client
        self._priority = priority
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
            poller = WorldPoller(world, self._client, self._sheets, self.listeners, self._interval, self._priority)
            self._pollers[world] = poller
            poller.start()
            log.info("Started polling %s", world)

    async def stop_all(self) -> None:
        await self.sync(set())
