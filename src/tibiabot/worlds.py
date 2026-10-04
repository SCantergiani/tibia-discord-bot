"""The list of live Tibia worlds, refreshed hourly, and world-name normalisation."""

from __future__ import annotations

import logging
import time

from tibiabot.tibiadata.client import TibiaDataClient, TibiaDataError

log = logging.getLogger(__name__)


def formal(world: str) -> str:
    """'aNtIcA ' -> 'Antica', the form stored in `worlds.name`."""
    return world.strip().lower().capitalize()


class WorldList:
    def __init__(self, client: TibiaDataClient, ttl: float = 3600):
        self._client = client
        self._ttl = ttl
        self._names: list[str] = []
        self._fetched_at = 0.0

    async def names(self) -> list[str]:
        if not self._names or time.time() - self._fetched_at > self._ttl:
            try:
                self._names = sorted(w.name for w in await self._client.worlds())
                self._fetched_at = time.time()
            except TibiaDataError as e:
                # A stale list beats refusing every /init during an outage.
                log.warning("World list refresh failed: %s", e)
        return self._names

    async def resolve(self, world: str) -> str | None:
        wanted = formal(world)
        return wanted if wanted in await self.names() else None
