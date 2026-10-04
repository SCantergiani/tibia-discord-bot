"""HTTP client for TibiaData v4, with retries and a bound on requests in flight."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, TypeVar
from urllib.parse import quote

import aiohttp

from tibiabot.tibiadata.models import Character, Guild, KillStatistics, World, WorldSummary, worlds_from_json

log = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE = frozenset({500, 502, 503, 504})
MAX_RETRIES = 2
USER_AGENT = "tibiabot-python (self-hosted)"


class TibiaDataError(Exception):
    pass


class NotFound(TibiaDataError):
    """The name resolves to nothing: deleted, renamed, or never existed."""


class TibiaDataClient:
    def __init__(self, base_url: str, max_in_flight: int = 32, session: aiohttp.ClientSession | None = None,
                 on_pushback: Callable[[int], None] | None = None):
        # Told every refusal or upstream failure status, so the request rate can back off.
        self.on_pushback = on_pushback
        self._base = base_url.rstrip("/")
        self._limit = asyncio.Semaphore(max_in_flight)
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> TibiaDataClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20),
                headers={"User-Agent": USER_AGENT},
            )
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self._base}{path}"
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with self._limit, self._http().get(url) as resp:
                    if resp.status not in (200, 404) and self.on_pushback:
                        self.on_pushback(resp.status)
                    if resp.status == 200:
                        return await resp.json(content_type=None)
                    if resp.status == 404:
                        raise NotFound(url)
                    if resp.status == 429:
                        # Not retried here: the next poll is the retry.
                        raise TibiaDataError(f"rate limited by {url}")
                    if resp.status not in RETRYABLE or attempt == MAX_RETRIES:
                        raise TibiaDataError(f"HTTP {resp.status} from {url}")
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == MAX_RETRIES:
                    raise TibiaDataError(f"{url}: {e!r}") from e
            delay = 0.5 * 2 ** attempt + random.uniform(0, 0.25)
            log.debug("Retrying %s in %.2fs", url, delay)
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _fetch(self, path: str, parse: Callable[[dict], T]) -> T:
        data = await self._get_json(path)
        try:
            return parse(data)
        except (KeyError, TypeError, ValueError) as e:
            raise TibiaDataError(f"could not parse {path}: {e!r}") from e

    async def world(self, name: str) -> World:
        return await self._fetch(f"/v4/world/{quote(name)}", World.from_json)

    async def worlds(self) -> list[WorldSummary]:
        return await self._fetch("/v4/worlds", worlds_from_json)

    async def character(self, name: str) -> Character:
        data = await self._get_json(f"/v4/character/{quote(name)}")
        # TibiaData answers an unknown name with 200 and an empty character.
        if not ((data.get("character") or {}).get("character") or {}).get("name"):
            raise NotFound(name)
        try:
            return Character.from_json(data)
        except (KeyError, TypeError, ValueError) as e:
            raise TibiaDataError(f"could not parse character {name!r}: {e!r}") from e

    async def guild(self, name: str) -> Guild:
        return await self._fetch(f"/v4/guild/{quote(name)}", Guild.from_json)

    async def kill_statistics(self, world: str) -> KillStatistics:
        return await self._fetch(f"/v4/killstatistics/{quote(world)}", KillStatistics.from_json)
