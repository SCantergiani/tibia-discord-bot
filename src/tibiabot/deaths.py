"""Death and level-up detection from the world poll, and how a death is written up
for one Discord server. Ported from TibiaBot.scala's scan and post stages.

Detection happens once per world; the write-up happens per server, because
colours, pings and filters depend on that server's lists and settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import asyncpg

from tibiabot import creatures, emojis, killers
from tibiabot.db.repos import WorldConfig
from tibiabot.lists.embeds import VOCATION_EMOJI, char_url, guild_url, vocation_key
from tibiabot.lists.models import GuildLists
from tibiabot.poller import WorldSnapshot
from tibiabot.tibiadata.models import Character, Death

log = logging.getLogger(__name__)

RECENT_DEATH = timedelta(minutes=30)
RECENTLY_DIED = timedelta(minutes=10)
LEVEL_MEMORY = timedelta(hours=25)
DESCRIPTION_LIMIT = 4065

# Embed colours. Which bucket a death falls in decides the show/hide filter.
NEUTRAL = 3092790
NEUTRAL_GUILD = 4540237
CUSTOM_SORT = 14397256
PVP_NEUTRAL = 14869218
ALLY = 0x2ECC71   # green
ENEMY = 0xE74C3C  # red
NEMESIS = 11563775
_NEUTRAL_COLORS = {NEUTRAL, PVP_NEUTRAL, NEUTRAL_GUILD, CUSTOM_SORT}


def vocation_emoji(vocation: str) -> str:
    return VOCATION_EMOJI.get(vocation_key(vocation), "")


# --- detection --------------------------------------------------------------

class DeathDetector:
    """New deaths on a sheet: younger than 30 minutes and not seen before. Seen
    deaths are kept in `bot_cache.deaths`, so a restart doesn't repost them."""

    def __init__(self, cache: asyncpg.Pool):
        self._cache = cache
        self._seen: dict[str, set[tuple[str, datetime]]] = {}

    async def load(self, world: str) -> None:
        rows = await self._cache.fetch("SELECT name, time FROM deaths WHERE world = $1", world)
        seen = self._seen.setdefault(world, set())
        for r in rows:
            try:
                seen.add((r["name"], datetime.fromisoformat(r["time"].replace("Z", "+00:00"))))
            except ValueError:
                continue

    async def detect(self, snapshot: WorldSnapshot, now: datetime | None = None) -> list[tuple[Character, Death]]:
        now = now or datetime.now(timezone.utc)
        if snapshot.world not in self._seen:
            await self.load(snapshot.world)
        seen = self._seen[snapshot.world]
        found: list[tuple[Character, Death]] = []
        for character in snapshot.characters.values():
            for death in character.deaths:
                key = (character.name, death.time)
                if now - death.time < RECENT_DEATH and key not in seen:
                    seen.add(key)
                    found.append((character, death))
        if found:
            await self._cache.executemany("INSERT INTO deaths (world, name, time) VALUES ($1, $2, $3)",
                                          [(snapshot.world, c.name, d.time.isoformat()) for c, d in found])
        self._seen[snapshot.world] = {k for k in seen if now - k[1] < RECENT_DEATH}
        return sorted(found, key=lambda pair: pair[1].time)

    async def prune(self, now: datetime | None = None) -> None:
        cutoff = ((now or datetime.now(timezone.utc)) - RECENT_DEATH).isoformat()
        await self._cache.execute("DELETE FROM deaths WHERE time < $1", cutoff)


@dataclass(frozen=True)
class LevelUp:
    character: Character
    level: int
    vocation: str


class LevelDetector:
    """A level-up is the online list showing a higher level than the sheet, unless
    the sheet shows a death in the last 10 minutes (a death costs levels, and the
    lists disagree until the sheet catches up). Each (name, level) is posted once
    per login, remembered for 25 hours in `bot_cache.levels`."""

    def __init__(self, cache: asyncpg.Pool):
        self._cache = cache
        self._seen: dict[str, dict[tuple[str, int], datetime]] = {}

    async def load(self, world: str) -> None:
        seen = self._seen.setdefault(world, {})
        for r in await self._cache.fetch("SELECT name, level, last_login FROM levels WHERE world = $1", world):
            try:
                seen[(r["name"], int(r["level"]))] = datetime.fromisoformat(r["last_login"].replace("Z", "+00:00"))
            except ValueError:
                continue

    def _should_record(self, world: str, name: str, level: int, last_login: datetime) -> bool:
        known = self._seen[world].get((name, level))
        return known is None or known < last_login

    async def detect(self, snapshot: WorldSnapshot, now: datetime | None = None) -> list[LevelUp]:
        now = now or datetime.now(timezone.utc)
        if snapshot.world not in self._seen:
            await self.load(snapshot.world)
        online = {p.name: p for p in snapshot.online}
        found: list[LevelUp] = []
        for name, player in online.items():
            sheet = snapshot.characters.get(name)
            if sheet is None or player.level <= sheet.level:
                continue
            if any(now - d.time <= RECENTLY_DIED for d in sheet.deaths):
                continue
            last_login = sheet.last_login or datetime(2022, 1, 1, tzinfo=timezone.utc)
            if self._should_record(snapshot.world, name, player.level, last_login):
                self._seen[snapshot.world][(name, player.level)] = last_login
                found.append(LevelUp(sheet, player.level, player.vocation or sheet.vocation))
        if found:
            await self._cache.executemany(
                "INSERT INTO levels (world, name, level, vocation, last_login, time) VALUES ($1, $2, $3, $4, $5, $6)",
                [(snapshot.world, u.character.name, str(u.level), u.vocation,
                  (u.character.last_login or now).isoformat(), now.isoformat()) for u in found])
        return found

    async def prune(self, now: datetime | None = None) -> None:
        cutoff = ((now or datetime.now(timezone.utc)) - LEVEL_MEMORY).isoformat()
        await self._cache.execute("DELETE FROM levels WHERE time < $1", cutoff)


# --- relations --------------------------------------------------------------

@dataclass(frozen=True)
class Relation:
    ally_guild: bool
    hunted_guild: bool
    ally_player: bool
    hunted_player: bool

    @property
    def ally(self) -> bool:
        return self.ally_guild or self.ally_player

    @property
    def enemy(self) -> bool:
        return self.hunted_guild or self.hunted_player

    @property
    def side(self) -> str:
        """One side, by the icon precedence: the guild's relation before the player's."""
        if self.ally_guild:
            return "ally"
        if self.hunted_guild:
            return "enemy"
        if self.ally_player:
            return "ally"
        if self.hunted_player:
            return "enemy"
        return "neutral"


def relation_of(lists: GuildLists, name: str, guild_name: str | None) -> Relation:
    g = (guild_name or "").lower()
    return Relation(bool(g) and g in lists.allied_guilds, bool(g) and g in lists.hunted_guilds,
                    name.lower() in lists.allied_players, name.lower() in lists.hunted_players)


def guild_icon(guild_name: str | None, rel: Relation) -> str:
    """Matches GuildIcons.classify: guild relation first, then the player's own."""
    e = emojis.get
    if rel.ally_guild:
        return e("allyguild")
    if rel.hunted_guild:
        return e("enemyguild")
    if rel.ally_player:
        return e("ally") if not guild_name else e("neutralguild") + e("ally")
    if rel.hunted_player:
        return e("enemy") if not guild_name else e("neutralguild") + e("enemy")
    return "" if not guild_name else e("neutralguild")


# --- the death write-up -----------------------------------------------------

@dataclass
class DeathPost:
    """Everything one server needs to post one death."""
    victim: str
    vocation: str
    level: int
    time: datetime
    color: int
    thumbnail: str
    description: str
    poke: str  # "", "nemesis", "allypk", "fullbless", "screenshot"
    killer: str
    frag_killers: list[str] = field(default_factory=list)
    relation: Relation | None = None

    @property
    def title(self) -> str:
        voc = vocation_emoji(self.vocation)
        return f"{voc} {self.victim} {voc}".strip()

    @property
    def side_label(self) -> str | None:
        """A banner above the title, so whose death it is reads at a glance."""
        return {ALLY: "🟩 ALLY DIED", ENEMY: "🟥 ENEMY DIED"}.get(self.color)

    @property
    def url(self) -> str:
        return char_url(self.victim)

    def visible(self, world: WorldConfig) -> bool:
        if self.color in _NEUTRAL_COLORS:
            return world.show_neutral_deaths != "false"
        if self.color == ENEMY:
            return world.show_enemies_deaths != "false"
        if self.color == ALLY:
            return world.show_allies_deaths != "false"
        return True


def exiva_blocks(names: list[str]) -> str:
    """One code block per spell, so Discord gives each its own copy button."""
    if not names:
        return ""
    return f"\n{emojis.get('exiva')}" + "".join(f"\n```\nexiva \"{n}\"\n```" for n in names)


def build_death(character: Character, death: Death, lists: GuildLists, world: WorldConfig,
                killer_levels: dict[str, int], custom_sort: set[tuple[str, str]] = frozenset()) -> DeathPost:
    """`custom_sort` holds ("guild"|"player", lowercase name) pairs from online_list_categories."""
    name = character.name
    last_killer = death.killers[-1].name if death.killers else "Invalid"
    context = "Died"
    color = NEUTRAL
    thumbnail = creatures.death_thumbnail(last_killer)
    poke = ""
    killer_parts: list[str] = []
    exiva: list[tuple[str, int | None]] = []
    frags: list[str] = []
    guild_text = ""
    rel = relation_of(lists, name, character.guild_name)

    if character.guild_name:
        color = NEUTRAL_GUILD
        if ("guild", character.guild_name.lower()) in custom_sort:
            color = CUSTOM_SORT
        icon = emojis.get("neutralguild")
        if rel.ally_guild:
            color, icon = ALLY, emojis.get("allyguild")
        if rel.hunted_guild:
            color, poke = ENEMY, "fullbless"
        guild_text = (f"{icon} *{character.guild_rank or ''}* of the "
                      f"[{character.guild_name}]({guild_url(character.guild_name)})\n")
    if ("player", name.lower()) in custom_sort:
        color = CUSTOM_SORT
    if rel.ally_player:
        color = ALLY
    if rel.hunted_player:
        color, poke = ENEMY, "fullbless"
    if creatures.is_notable(last_killer):
        color, poke = NEMESIS, "nemesis"

    def level_text(player: str) -> str:
        level = killer_levels.get(player.lower())
        return f" [{level}]" if level is not None else ""

    for k in death.killers:
        if k.player:
            if k.name == name:
                continue  # 'self' entries
            context = "Killed"
            poke = "allypk" if rel.ally else "screenshot" if rel.enemy else ""
            if color in (NEUTRAL, NEUTRAL_GUILD):
                color = PVP_NEUTRAL
            thumbnail = creatures.PVP_THUMBNAIL
            behind = killers.summon_behind(k.name, k.summon)
            if behind:
                creature, summoner = behind
                killer_parts.append(f"{killers.article(creature)} {emojis.get('summon')} **{creature} of "
                                    f"[{summoner}{level_text(summoner)}]({char_url(summoner)})**")
                frags.append(summoner)
                if color == ALLY and world.exiva_list == "true":
                    exiva.append((summoner, killer_levels.get(summoner.lower())))
            else:
                killer_parts.append(f"**[{k.name}{level_text(k.name)}]({char_url(k.name)})**")
                frags.append(k.name)
                if color == ALLY and world.exiva_list == "true":
                    exiva.append((k.name, killer_levels.get(k.name.lower())))
        else:
            article = killers.source_article(k.name) if not any(ch.isupper() for ch in k.name) else ""
            killer_parts.append(f"{article}{creatures.boss_emoji(k.name)}**{k.name}**")

    exiva_names = killers.exiva_targets(exiva, world.exiva_count or len(exiva))

    header = f"{guild_text}{context} <t:{int(death.time.timestamp())}:R> at level {death.level}"
    if not killer_parts:
        thumbnail = creatures.SUICIDE_THUMBNAIL
        killer_parts = ["`suicide`"]
    room = DESCRIPTION_LIMIT - len(f"{header}\nby .")
    # Exivas get at most half the room, dropping the lowest levels, so a long list
    # never leaves a code block cut open.
    while len(exiva_blocks(exiva_names)) > room // 2:
        exiva_names.pop()
    exiva_text = exiva_blocks(exiva_names)
    killer_text = killers.join_within(killer_parts, room - min(len(exiva_text), room // 2))
    text = f"{header}\nby {killer_text}.{exiva_text}"
    if len(text) > DESCRIPTION_LIMIT:
        text = text[:text.rfind("\n", 0, DESCRIPTION_LIMIT)] + "\n:scissors: `out of space`"

    return DeathPost(victim=name, vocation=character.vocation, level=death.level, time=death.time, color=color,
                     thumbnail=thumbnail, description=text, poke=poke, killer=last_killer,
                     frag_killers=list(dict.fromkeys(frags)), relation=rel)


def level_line(up: LevelUp, lists: GuildLists) -> tuple[str, Relation]:
    rel = relation_of(lists, up.character.name, up.character.guild_name)
    icon = guild_icon(up.character.guild_name, rel)
    line = (f"{vocation_emoji(up.vocation)} **[{up.character.name}]({char_url(up.character.name)})** advanced to "
            f"{emojis.get('levelup')} level **{up.level}** {icon}").rstrip()
    return line, rel


def level_visible(rel: Relation, level: int, world: WorldConfig) -> bool:
    shown = {"ally": world.show_allies_levels, "enemy": world.show_enemies_levels,
             "neutral": world.show_neutral_levels}[rel.side]
    return shown != "false" and level >= world.levels_min


def online_levels(snapshot: WorldSnapshot) -> dict[str, int]:
    return {p.name.lower(): p.level for p in snapshot.online}


def killer_names(found: list[tuple[Character, Death]]) -> set[str]:
    names: set[str] = set()
    for character, death in found:
        names.update(killers.level_lookup_names(character.name, [(k.name, k.player) for k in death.killers]))
    return names

