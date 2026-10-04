"""Hunted/allied list entries and the decisions about them that need no I/O:
reading a pasted list of names, tags, the outcome of a bulk change, and when a
listed player should be flagged for removal."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import timedelta

MAX_NAMES = 100
GRACE_BEFORE_REMOVAL = timedelta(days=7)


@dataclass(frozen=True)
class ListedPlayer:
    """One row of `hunted_players` / `allied_players`. `name` is stored lowercase."""
    name: str
    reason: str = "false"
    reason_text: str = "none"
    added_by: str = ""
    traded_when_added: bool = False
    flagged_reason: str = ""
    flagged_at: str = ""
    tag: str = ""

    def with_(self, **changes) -> ListedPlayer:
        return replace(self, **changes)


@dataclass(frozen=True)
class ListedGuild:
    name: str
    reason: str = "false"
    reason_text: str = "none"
    added_by: str = ""


@dataclass
class GuildLists:
    """One Discord server's hunted and allied lists, keyed by lowercase name."""
    hunted_players: dict[str, ListedPlayer] = field(default_factory=dict)
    hunted_guilds: dict[str, ListedGuild] = field(default_factory=dict)
    allied_players: dict[str, ListedPlayer] = field(default_factory=dict)
    allied_guilds: dict[str, ListedGuild] = field(default_factory=dict)

    def players(self, hunted: bool) -> dict[str, ListedPlayer]:
        return self.hunted_players if hunted else self.allied_players

    def guilds(self, hunted: bool) -> dict[str, ListedGuild]:
        return self.hunted_guilds if hunted else self.allied_guilds


# --- tags -------------------------------------------------------------------

@dataclass(frozen=True)
class Tag:
    key: str
    label: str
    emoji: str


TAGS: list[Tag] = [
    Tag("bot", "Bot", "🤖"), Tag("toxic", "Toxic", "🤬"), Tag("carbomber", "Carbomber", "🪤"),
    Tag("bomb", "Bomb", "💣"), Tag("thief", "Thief", "🥷"), Tag("rat", "Rat", "🐀"),
    Tag("killer", "Killer", "⚔️"), Tag("tank", "Tank", "🛡️"), Tag("leader", "Leader", "👑"),
    Tag("rich", "Rich", "💰"), Tag("priority", "Priority", "🎯"), Tag("inactive", "Inactive", "🧊"),
    Tag("unknown", "Unknown", "❓"),
]
NO_TAG = "none"
_TAGS_BY_KEY = {t.key: t for t in TAGS}


def find_tag(key: str | None) -> Tag | None:
    if not key or key == NO_TAG:
        return None
    return _TAGS_BY_KEY.get(key.lower())


def tag_mark(key: str | None) -> str:
    tag = find_tag(key)
    return f" {tag.emoji}" if tag else ""


# --- pasted names -----------------------------------------------------------

_DECORATION = re.compile(r"^\s*(?:[-*•‣▪]|\d{1,3}[.)])\s+")
_WRAPPING = re.compile(r"""^[\s"'`*_\[\]]+|[\s"'`*_\[\]]+$""")


def parse_names(pasted: str | None) -> list[str]:
    """One name per line (or comma/semicolon/tab separated), bullets and quotes
    stripped, implausible lengths dropped, duplicates removed case-insensitively."""
    seen: set[str] = set()
    names: list[str] = []
    for line in (pasted or "").split("\n"):
        for raw in re.split(r"[,;\t]", line):
            name = _WRAPPING.sub("", _DECORATION.sub("", raw, count=1)).strip()
            if 2 <= len(name) <= 29 and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
    return names


def capitalize_words(name: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in name.split(" "))


# --- bulk outcome -----------------------------------------------------------

@dataclass
class BulkOutcome:
    added: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def merge(self, other: BulkOutcome) -> BulkOutcome:
        return BulkOutcome(self.added + other.added, self.already + other.already,
                           self.not_found + other.not_found, self.unavailable + other.unavailable,
                           self.skipped + other.skipped)

    @property
    def changed_anything(self) -> bool:
        return bool(self.added)


# --- review -----------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """Why a listed player should come off the list. `reason` is what's stored."""
    reason: str
    detail: str = ""


GONE = Finding("gone")
TRADED = Finding("traded")


def scheduled_for_deletion(date: str) -> Finding:
    return Finding("deletion", date)


def moved_world(world: str) -> Finding:
    return Finding("world", world)


def review(entry: ListedPlayer, traded: bool, world: str, tracked_worlds: set[str],
           deletion_date: str | None = None) -> Finding | None:
    """Flag at most once. A trade only counts if it happened after the player was
    listed; a move only counts away from every world this server tracks."""
    if entry.flagged_reason:
        return None
    if deletion_date:
        return scheduled_for_deletion(deletion_date)
    if traded and not entry.traded_when_added:
        return TRADED
    if world and tracked_worlds and world.lower() not in {w.lower() for w in tracked_worlds}:
        return moved_world(world)
    return None


def review_missing(entry: ListedPlayer) -> Finding | None:
    return None if entry.flagged_reason else GONE
