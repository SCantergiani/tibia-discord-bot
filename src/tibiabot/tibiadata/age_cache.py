"""Skips re-fetching a character sheet until TibiaData's own copy has turned over.

TibiaData's upstream cache holds `/v4/character` for about 300s, stamped with
`information.timestamp` when it was built. Asking again before that copy expires
returns identical bytes, so the cache keeps the sheet until origin + ttl. A
failed fetch is covered by the stored sheet for up to `max_stale` seconds.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Awaitable, Callable

from tibiabot.tibiadata.models import Character


@dataclass
class _Entry:
    character: Character
    fresh_until: float
    fetched_at: float


class CharacterAgeCache:
    def __init__(self, fetch: Callable[[str], Awaitable[Character]], ttl: float = 300,
                 max_stale: float = 900, max_entries: int = 20000,
                 clock: Callable[[], float] = time.time):
        self._fetch = fetch
        self._ttl = ttl
        self._max_stale = max_stale
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def peek(self, name: str) -> Character | None:
        entry = self._entries.get(name.lower())
        return entry.character if entry else None

    async def get(self, name: str, fresh: bool = False) -> Character:
        """`fresh` skips the stored copy (still used to cover a failed fetch):
        worth it only against a TibiaData that doesn't cache, see poller.py."""
        key = name.lower()
        now = self._clock()
        entry = self._entries.get(key)
        if entry and now < entry.fresh_until and not fresh:
            return entry.character
        try:
            character = await self._fetch(name)
        except Exception:
            if entry and now - entry.fetched_at <= self._max_stale:
                return entry.character
            raise
        origin = character.origin_timestamp.timestamp() if character.origin_timestamp else now
        # Never trust an origin from the future or older than a full ttl ago:
        # either way the safe answer is "fresh for one ttl from now at most".
        origin = min(max(origin, now - self._ttl), now)
        self._entries[key] = _Entry(character, origin + self._ttl, now)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return character

    def forget(self, name: str) -> None:
        self._entries.pop(name.lower(), None)
