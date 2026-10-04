"""`/lootsplit`: a form to paste a party hunt analyser into, and the split back.

A good split is a normal message (people copy from it later); a paste that
didn't read is ephemeral, so the channel isn't left holding a typo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from tibiabot import embeds, emojis, lootsplit, lootsplit_embeds

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

PLACEHOLDER = "Session data: From 2026-09-01, 21:12:00 to 2026-09-01, 23:29:40"


class LootSplitModal(discord.ui.Modal, title="Loot split"):
    analyser = discord.ui.TextInput(
        label="Paste your party hunt analyser",
        style=discord.TextStyle.paragraph,
        placeholder=PLACEHOLDER,
        max_length=4000,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        pasted = self.analyser.value
        try:
            hunt = lootsplit.parse(pasted)
        except lootsplit.ParseError as problem:
            await interaction.response.send_message(embed=embeds.error(str(problem)), ephemeral=True)
            return
        await interaction.response.send_message(embed=lootsplit_embeds.session(hunt, emojis.get("gold")),
                                                file=lootsplit_embeds.paste(pasted))


class LootSplitCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot

    @app_commands.command(name="lootsplit", description="Split a party hunt from your hunt analyser")
    async def lootsplit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(LootSplitModal())


async def setup(bot: TibiaBot) -> None:
    await bot.add_cog(LootSplitCog(bot))
