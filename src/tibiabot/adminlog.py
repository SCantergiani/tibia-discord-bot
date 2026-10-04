"""Posts to a server's command-log channel: what someone did, or what the bot did
on its own (a different colour, so the two read apart)."""

from __future__ import annotations

import logging

import discord

from tibiabot import embeds
from tibiabot.db.repos import DiscordInfo

log = logging.getLogger(__name__)

AUTOMATIC_COLOR = 14397256
COMMAND_TITLE = ":gear: a command was run:"


def user(name: str) -> str:
    cleaned = name.replace("`", "").strip()
    return f"**`{cleaned}`**" if cleaned else "**`someone`**"


async def post(guild: discord.Guild, info: DiscordInfo | None, description: str, thumbnail: str,
               title: str = COMMAND_TITLE, automatic: bool = False) -> None:
    channel = guild.get_channel(int(info.admin_channel)) if info and info.admin_channel.isdigit() else None
    if not isinstance(channel, discord.TextChannel):
        return
    embed = discord.Embed(title=title, description=description,
                          color=AUTOMATIC_COLOR if automatic else embeds.BRAND_COLOR)
    embed.set_thumbnail(url=thumbnail)
    try:
        await channel.send(embed=embed)
    except discord.HTTPException as e:
        log.warning("Could not post to the command log in %s: %s", guild.id, e)
