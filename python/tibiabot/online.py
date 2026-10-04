"""Who is online on a world, and how one server's online list is written.

Ported from OnlineTracker, OnlineListGrouping, OnlineListEmbeds and
MasslogDetector, simplified to the combined layout (one channel)."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field

from tibiabot import emojis
from tibiabot.db.repos import WorldConfig
from tibiabot.deaths import Relation, guild_icon, relation_of, vocation_emoji
from tibiabot.lists.embeds import VOCATION_ORDER, char_url, guild_url, vocation_key
from tibiabot.lists.models import GuildLists, tag_mark
from tibiabot.tibiadata.models import OnlinePlayer

RECENT_LOGIN_SECONDS = 900      # :zap: for an enemy online less than this
LONG_SESSION_SECONDS = 5 * 3600  # :zzz: for an enemy online longer than this
MESSAGE_BUDGET = 5900
EMBED_BUDGET = MESSAGE_BUDGET // 2
HEADER_HEADROOM = 210
MAX_EMBEDS_PER_MESSAGE = 10


@dataclass
class Seen:
    since: float
    known_start: bool  # False: already online when the bot started, real start unknown
    flag: str = ""


@dataclass
class WorldOnline:
    """One world's online players with how long each has been on, from the polls."""
    players: dict[str, OnlinePlayer] = field(default_factory=dict)
    seen: dict[str, Seen] = field(default_factory=dict)
    updated: float = 0.0

    def update(self, online: list[OnlinePlayer], first_poll: bool, now: float | None = None) -> None:
        now = now or time.time()
        current = {p.name: p for p in online}
        self.seen = {n: s for n, s in self.seen.items() if n in current}
        for name in current:
            if name not in self.seen:
                self.seen[name] = Seen(now, known_start=not first_poll)
        self.players = current
        self.updated = now

    def duration(self, name: str, now: float | None = None) -> tuple[int, bool]:
        s = self.seen.get(name)
        return (int((now or time.time()) - s.since), s.known_start) if s else (0, False)

    def set_flag(self, name: str, flag: str) -> None:
        if name in self.seen:
            self.seen[name].flag = flag


def duration_text(seconds: int, known: bool) -> str:
    minutes = seconds // 60
    text = f"{minutes // 60}hr {minutes % 60}min" if minutes >= 60 else f"{minutes}min"
    return f"`{text}{'' if known else '+'}`"


def channel_name(base: str, allies: int, enemies: int, masslog: bool) -> str:
    """'📈・ᴏɴʟɪɴᴇ' + '・🤍3💀2⚡': allies and enemies online, ⚡ during a mass log."""
    suffix = (f"🤍{allies}" if allies else "") + (f"💀{enemies}" if enemies else "") + ("⚡" if masslog else "")
    return f"{base}・{suffix}" if suffix else base


# Strips what the bot appended: the counts above, or the Scala bot's '-<total>'.
_NAME_SUFFIX = re.compile(r"^(.*?)(?:-(?:[0-9]+|⚠️)|・(?=[🤍💀⚡])(?:🤍[0-9]+)?(?:💀[0-9]+)?⚡?)?$")


def base_name(channel_name: str, default: str) -> str:
    m = _NAME_SUFFIX.match(channel_name)
    return m.group(1) if m and m.group(1) else default


# --- masslog ----------------------------------------------------------------

def required_zaps(enemies: int, floor: int = 3) -> int:
    base = 0.60 if enemies <= 5 else 0.55 if enemies <= 10 else 0.40 if enemies <= 20 else 0.32
    return max(floor, math.ceil(enemies * base * 1.20))


def is_masslog(zaps: int, enemies: int) -> bool:
    return zaps >= required_zaps(enemies)


# --- one server's list ------------------------------------------------------

@dataclass
class Row:
    guild: str
    relation: Relation
    vocation: str
    level: int
    line: str


@dataclass
class OnlineList:
    lines: list[str]
    allies: int
    enemies: int
    total: int
    masslog: bool
    fresh_enemies: list[str] = field(default_factory=list)  # lines of enemies who just logged in


MASSLOG_EVERYONE = "everyone"


def masslog_mode(world: WorldConfig) -> str:
    """"role", "everyone" or "off", read from the masslog_role column."""
    value = world.masslog_role or "0"
    if value == MASSLOG_EVERYONE:
        return "everyone"
    return "role" if value.isdigit() and value != "0" else "off"


def build(world_online: WorldOnline, lists: GuildLists, world: WorldConfig, guild_of: dict[str, str],
          now: float | None = None) -> OnlineList:
    """`guild_of` maps a character name to its guild, from whatever sheets are known."""
    now = now or time.time()
    rows: list[Row] = []
    zaps = 0
    fresh: list[str] = []
    for player in sorted(world_online.players.values(), key=lambda p: -p.level):
        guild = guild_of.get(player.name, "")
        rel = relation_of(lists, player.name, guild)
        seconds, known = world_online.duration(player.name, now)
        enemy = rel.enemy
        just_logged = known and seconds < RECENT_LOGIN_SECONDS and enemy and player.level >= world.online_enemies_min
        zaps += just_logged
        mark = " :zap:" if just_logged else " :zzz:" if enemy and seconds > LONG_SESSION_SECONDS else ""
        flag = world_online.seen[player.name].flag if player.name in world_online.seen else ""
        tag = tag_mark(lists.hunted_players[player.name.lower()].tag) if player.name.lower() in lists.hunted_players \
            else ""
        line = (f"{vocation_emoji(player.vocation)} **{player.level}** — **[{player.name}]({char_url(player.name)})** "
                f"{guild_icon(guild, rel)} {duration_text(seconds, known)} {flag}{mark}{tag}")
        rows.append(Row(guild, rel, vocation_key(player.vocation), player.level, re.sub(r"\s+$", "", line)))
        if just_logged:
            fresh.append(rows[-1].line)

    order = {v: i for i, v in enumerate(VOCATION_ORDER)}
    rows.sort(key=lambda r: (order.get(r.vocation, len(order)), -r.level))

    def side(r: Row) -> str:
        return r.relation.side

    # Only allies and enemies are listed; everyone else on the world is left out.
    allies = [r for r in rows if side(r) == "ally" and r.level >= world.online_allies_min]
    enemies = [r for r in rows if side(r) == "enemy" and r.level >= world.online_enemies_min]
    e = emojis.get
    lines: list[str] = []
    for title, icon, section in (("Allies", e("ally"), allies), ("Enemies", e("enemy"), enemies)):
        if section:
            lines.append(f"## {icon} {title} {len(section)}")
            lines += with_headers(group_by_guild([(r.guild, r.line) for r in section]), lambda n: f"### No guild {n}")
    return OnlineList(lines, len(allies), len(enemies), len(allies) + len(enemies),
                      is_masslog(zaps, len(enemies)) if enemies else False, fresh)


def group_by_guild(rows: list[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    """Guilds biggest first (ties keep first appearance), guildless last."""
    groups: dict[str, list[str]] = {}
    for guild, line in rows:
        groups.setdefault(guild, []).append(line)
    with_guild = sorted(((g, ls) for g, ls in groups.items() if g), key=lambda gl: -len(gl[1]))
    return with_guild + ([("", groups[""])] if "" in groups else [])


def with_headers(grouped: list[tuple[str, list[str]]], guildless_header) -> list[str]:
    out: list[str] = []
    for guild, lines in grouped:
        out.append(guildless_header(len(lines)) if not guild else f"### [{guild}]({guild_url(guild)}) {len(lines)}")
        out.extend(lines)
    return out


# --- packing into messages --------------------------------------------------

def _is_header(line: str) -> bool:
    return line.startswith("### ") or line.startswith("## ")


def _is_section_header(line: str) -> bool:
    return (line.startswith("### ") and not line.startswith("### [")) or line.startswith("## ")


def pack_messages(values: list[str]) -> list[list[str]]:
    """Lines -> messages of embed descriptions. A message carries at most 10 embeds
    and ~5,900 characters; a section header starts a new embed; a header is never
    left at the end of an embed without the rows it introduces."""
    messages: list[list[str]] = []
    embeds: list[str] = []
    field_ = ""
    used = 0
    follows = [0] * len(values)
    keeps = 0
    for i in range(len(values) - 1, -1, -1):
        line = values[i]
        follows[i] = keeps if _is_header(line) else 0
        keeps = keeps + len(line) + 1 if _is_header(line) else len(line) + 1

    def embed_full(current: str, line: str) -> bool:
        return len(current) >= EMBED_BUDGET or (len(current) >= EMBED_BUDGET - HEADER_HEADROOM
                                                and line.startswith("### ["))

    for i, line in enumerate(values):
        current = field_ + "\n" + line
        if used + len(current) + follows[i] >= MESSAGE_BUDGET or embed_full(current, line) or (
                _is_section_header(line) and field_):
            embeds.append(field_)
            used += len(field_)
            if len(embeds) >= MAX_EMBEDS_PER_MESSAGE or used + len(line) + follows[i] >= MESSAGE_BUDGET:
                messages.append(embeds)
                embeds, used = [], 0
            field_ = line
        else:
            field_ = current
    embeds.append(field_)
    messages.append(embeds)
    return [[d.strip("\n") for d in m if d.strip("\n")] or ["​"] for m in messages]
