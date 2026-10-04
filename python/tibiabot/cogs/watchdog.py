"""`/watchdog`: a TibiaCardinal Watchdog room for a party.

A Watchdog room is nothing more than a name in the URL
(https://tibiacardinal.com/watchdog/<name>): everyone who opens the same link is
in the same room. So the bot invents a name nobody will guess and posts the link.
"""

from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from tibiabot import embeds

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

WATCHDOG_URL = "https://tibiacardinal.com/watchdog/"


def room_name(hint: str | None = None) -> str:
    """'popaco-<hint>-<8 random hex>', the hint reduced to lowercase letters, digits and dashes."""
    slug = re.sub(r"[^a-z0-9]+", "-", (hint or "").lower()).strip("-")[:24]
    return "-".join(part for part in ("popaco", slug, secrets.token_hex(4)) if part)


class WatchdogCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot

    @app_commands.command(name="watchdog", description="Open a TibiaCardinal Watchdog room for your party")
    @app_commands.describe(name="Optional, e.g. the hunt or respawn: it becomes part of the room's link")
    @app_commands.guild_only()
    async def watchdog(self, interaction: discord.Interaction, name: str | None = None) -> None:
        url = WATCHDOG_URL + room_name(name)
        embed = discord.Embed(
            title=":dog: Watchdog room", url=url, color=embeds.BRAND_COLOR,
            description=(f"{interaction.user.mention} opened a party room{f' for **{name}**' if name else ''}.\n"
                         "Everyone in the party: press **Join** and keep the tab open while you hunt.\n\n"
                         f"{url}"))
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Join", url=url, emoji="🐶"))
        await interaction.response.send_message(embed=embed, view=view,
                                                allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: TibiaBot) -> None:
    await bot.add_cog(WatchdogCog(bot))
