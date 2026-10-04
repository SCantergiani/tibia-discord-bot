"""Creature knowledge from the Scala bot's mappings.conf: which killers are rare
bosses worth a ping, which boss family icon a killer gets, and its wiki image."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from urllib.parse import quote

from tibiabot import emojis

WIKI_FILE = "https://www.tibiawiki.com.br/wiki/Special:Redirect/file/"

# Boss family -> emoji name (an uploaded image, see emojis.py). Order matters:
# the first family that lists a creature wins, same as BossEmoji.scala.
_FAMILIES = [
    ("nemesis-creatures", "nemesis"), ("archfoe-creatures", "archfoe"), ("bane-creatures", "bane"),
    ("boss-summons", "summon"), ("cube-bosses", "cube"), ("mk-bosses", "mortalcombat"),
    ("svar-green-bosses", "greenhorn"), ("svar-scrapper-bosses", "scrapper"), ("svar-warlord-bosses", "warlord"),
    ("zelos-bosses", "zelos"), ("library-bosses", "libfinal"), ("hod-bosses", "hodfinal"),
    ("feru-bosses", "ferufinal"), ("inq-bosses", "inq"), ("kilmaresh-bosses", "kilmaresh"),
    ("primal-creatures", "primal"), ("hazard-creatures", "hazard"),
]


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(resources.files("tibiabot.data").joinpath("mappings.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _notable() -> frozenset[str]:
    return frozenset(_data()["notable-creatures"])


def is_notable(killer: str) -> bool:
    """A rare boss whose kills ping the `<World> Rare Boss` role."""
    return killer.lower() in _notable()


def boss_emoji(name: str) -> str:
    lower = name.lower()
    for family, emoji_name in _FAMILIES:
        if lower in _data()[family]:
            icon = emojis.get(emoji_name)
            return f"{icon} " if icon else ""
    return ""


def title_case(creature: str) -> str:
    """'mooh'tah warrior' -> "Mooh'Tah Warrior", 'the voice of ruin' -> 'The Voice of Ruin'."""
    parsed = re.sub(r"([^\w]\w)", lambda m: m.group(1).upper(), creature)
    parsed = re.sub(r"( A| Of| The| In| On| To| And| With| From)(?= )", lambda m: m.group(1).lower(), parsed)
    return parsed[:1].upper() + parsed[1:]


def image_url(creature: str) -> str:
    mapped = _data()["creature-url-mappings"].get(creature.lower())
    return f"{WIKI_FILE}{quote(mapped or title_case(creature).replace(' ', '_'))}.gif"


# Death thumbnails by damage type. The Scala bot served these from its author's
# own site; the same animations come from TibiaWiki here.
PVP_THUMBNAIL = f"{WIKI_FILE}Phantasmal_Ooze.gif"
SUICIDE_THUMBNAIL = f"{WIKI_FILE}Ghost_Smoke_Effect.gif"
_DAMAGE_THUMBNAILS = {
    "death": "Death_Effect.gif", "ice": "Ice_Explosion_Effect.gif", "drowning": "Reaper_Effect.gif",
    "fire": "Fire.gif", "holy": "Holy_Effect.gif", "invalid": "Phantasmal_Ooze.gif",
    "life drain": "Red_Sparkles_Effect.gif", "mushroom": "Mushroom.gif",
}


def death_thumbnail(killer: str) -> str:
    file = _DAMAGE_THUMBNAILS.get(killer.lower())
    return f"{WIKI_FILE}{file}" if file else image_url(killer)
