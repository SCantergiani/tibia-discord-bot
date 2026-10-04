"""TibiaData v4 responses, reduced to the fields the bot reads.

Parsing is lenient on purpose: TibiaData omits empty fields (`omitempty`), so a
missing key means "none", never an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class OnlinePlayer:
    name: str
    level: int
    vocation: str


@dataclass(frozen=True)
class World:
    name: str
    status: str
    players_online: int
    pvp_type: str
    battleye_protected: bool
    online_players: list[OnlinePlayer]

    @classmethod
    def from_json(cls, data: dict) -> World:
        w = data["world"]
        return cls(
            name=w["name"],
            status=w.get("status", ""),
            players_online=int(w.get("players_online", 0)),
            pvp_type=w.get("pvp_type", ""),
            battleye_protected=bool(w.get("battleye_protected", False)),
            online_players=[OnlinePlayer(p["name"], int(p.get("level", 0)), p.get("vocation", ""))
                            for p in w.get("online_players") or []],
        )


@dataclass(frozen=True)
class WorldSummary:
    name: str
    pvp_type: str
    players_online: int


def worlds_from_json(data: dict) -> list[WorldSummary]:
    return [WorldSummary(w["name"], w.get("pvp_type", ""), int(w.get("players_online", 0)))
            for w in data["worlds"].get("regular_worlds") or []]


@dataclass(frozen=True)
class Killer:
    name: str
    player: bool
    traded: bool
    summon: str

    @classmethod
    def from_json(cls, k: dict) -> Killer:
        return cls(k.get("name", ""), bool(k.get("player", False)), bool(k.get("traded", False)),
                   k.get("summon", "") or "")


@dataclass(frozen=True)
class Death:
    time: datetime
    level: int
    killers: list[Killer]
    assists: list[Killer]
    reason: str


@dataclass(frozen=True)
class Character:
    name: str
    level: int
    vocation: str
    world: str
    sex: str
    guild_name: str | None
    guild_rank: str | None
    former_names: list[str]
    former_worlds: list[str]
    last_login: datetime | None
    account_status: str
    traded: bool
    deletion_date: str | None
    # Kept for the backlog's ownership check (a code pasted into the comment).
    comment: str
    deaths: list[Death] = field(default_factory=list)
    # When TibiaData's origin built this copy; drives the age cache.
    origin_timestamp: datetime | None = None

    @classmethod
    def from_json(cls, data: dict) -> Character:
        sheet = data["character"]
        c = sheet["character"]
        guild = c.get("guild") or {}
        deaths = []
        for d in sheet.get("deaths") or []:
            when = parse_time(d.get("time"))
            if when is None:
                continue
            deaths.append(Death(
                time=when,
                level=int(d.get("level", 0)),
                killers=[Killer.from_json(k) for k in d.get("killers") or []],
                assists=[Killer.from_json(k) for k in d.get("assists") or []],
                reason=d.get("reason", ""),
            ))
        return cls(
            name=c["name"],
            level=int(c.get("level", 0)),
            vocation=c.get("vocation", ""),
            world=c.get("world", ""),
            sex=c.get("sex", ""),
            guild_name=guild.get("name") or None,
            guild_rank=guild.get("rank") or None,
            former_names=list(c.get("former_names") or []),
            former_worlds=list(c.get("former_worlds") or []),
            last_login=parse_time(c.get("last_login")),
            account_status=c.get("account_status", ""),
            traded=bool(c.get("traded", False)),
            deletion_date=c.get("deletion_date") or None,
            comment=c.get("comment", "") or "",
            deaths=deaths,
            origin_timestamp=parse_time((data.get("information") or {}).get("timestamp")),
        )


@dataclass(frozen=True)
class GuildMember:
    name: str
    rank: str
    vocation: str
    level: int
    status: str


@dataclass(frozen=True)
class Guild:
    name: str
    world: str
    members: list[GuildMember]

    @classmethod
    def from_json(cls, data: dict) -> Guild:
        g = data["guild"]
        return cls(
            name=g.get("name", ""),
            world=g.get("world", ""),
            members=[GuildMember(m["name"], m.get("rank", ""), m.get("vocation", ""),
                                 int(m.get("level", 0)), m.get("status", ""))
                     for m in g.get("members") or []],
        )


@dataclass(frozen=True)
class KillStatisticsEntry:
    race: str
    last_day_killed: int
    last_day_players_killed: int
    last_week_killed: int
    last_week_players_killed: int


@dataclass(frozen=True)
class KillStatistics:
    world: str
    entries: list[KillStatisticsEntry]

    @classmethod
    def from_json(cls, data: dict) -> KillStatistics:
        k = data["killstatistics"]
        return cls(
            world=k.get("world", ""),
            entries=[KillStatisticsEntry(e["race"], int(e.get("last_day_killed", 0)),
                                         int(e.get("last_day_players_killed", 0)),
                                         int(e.get("last_week_killed", 0)),
                                         int(e.get("last_week_players_killed", 0)))
                     for e in k.get("entries") or []],
        )
