from __future__ import annotations

import discord

from tibiabot import emojis

BRAND_COLOR = 3092790
WIKI_FILE = "https://www.tibiawiki.com.br/wiki/Special:Redirect/file/"


def response(text: str) -> discord.Embed:
    return discord.Embed(description=text, color=BRAND_COLOR)


def ok(text: str) -> discord.Embed:
    return response(f"{emojis.get('yes')} {text}")


def error(text: str) -> discord.Embed:
    return response(f"{emojis.get('no')} {text}")


def channel_intro(text: str) -> discord.Embed:
    embed = response(text)
    embed.set_thumbnail(url=f"{WIKI_FILE}Sign_(Library).gif")
    return embed
