"""The bot's custom emojis, uploaded as *application* emojis owned by this bot.

The Scala config points at emoji ids in the original author's Discord server,
which another bot cannot render. Application emojis belong to the bot itself and
work in every server it is in, so on startup every image in the emoji folder that
the application does not have yet is uploaded under its file name.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import discord

log = logging.getLogger(__name__)

_VALID_NAME = re.compile(r"^[A-Za-z0-9_]{2,32}$")
_IMAGE_SUFFIXES = {".png", ".gif", ".jpg", ".jpeg", ".webp"}

# Shown when an emoji is missing (upload failed, or no image for it yet).
FALLBACKS: dict[str, str] = {
    "yes": "✅", "no": "❌", "levelup": "⬆️", "exiva": "🧭", "nemesis": "👹",
    "ally": "🟢", "enemy": "🔴", "allyguild": "🛡️", "enemyguild": "⚔️", "neutralguild": "⚪",
    "boss": "👑", "creature": "🐾", "hazard": "⚠️", "inq": "🕯️", "masslog": "📥",
    "summon": "🐉", "indent": "↳", "gold": "🪙", "letter": "✉️",
}

_registry: dict[str, str] = {}


def get(name: str) -> str:
    """`<:name:id>` for an uploaded emoji, else a Unicode stand-in, else ''."""
    return _registry.get(name) or FALLBACKS.get(name, "")


def loaded() -> dict[str, str]:
    return dict(_registry)


def local_images(folder: Path) -> dict[str, Path]:
    if not folder.is_dir():
        return {}
    return {p.stem: p for p in sorted(folder.iterdir())
            if p.suffix.lower() in _IMAGE_SUFFIXES and _VALID_NAME.match(p.stem)}


async def sync(client: discord.Client, folder: Path) -> None:
    """Upload missing images and load every application emoji into the registry."""
    existing = {e.name: e for e in await client.fetch_application_emojis()}
    for name, path in local_images(folder).items():
        if name in existing:
            continue
        try:
            existing[name] = await client.create_application_emoji(name=name, image=path.read_bytes())
            log.info("Uploaded application emoji %s", name)
        except discord.HTTPException as e:
            log.warning("Could not upload emoji %s: %s", name, e)
    _registry.clear()
    _registry.update({name: str(emoji) for name, emoji in existing.items()})
    log.info("%d application emojis ready", len(_registry))
