"""`/clear` (Manage Server): wipe a world's deaths and/or levels channel.

The channel is cloned (same name, position, permissions) and the old one
deleted: instant however many messages it holds, where deleting them one by one
is slow and Discord won't bulk-delete anything older than 14 days. The new
channel id is stored and the channel's intro is posted again.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from tibiabot import adminlog, embeds
from tibiabot.cogs.setup import WORLD_CHANNELS
from tibiabot.db import repos
from tibiabot.db.repos import WorldConfig
from tibiabot.permissions import has_manage_server

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

TARGETS = {"deaths": ["deaths_channel"], "levels": ["levels_channel"], "both": ["deaths_channel", "levels_channel"]}
INTROS = {column: intro for column, _, intro in WORLD_CHANNELS}


async def clear_channel(bot: TibiaBot, guild: discord.Guild, world: WorldConfig, column: str,
                        reason: str) -> discord.TextChannel | None:
    """Replace the world's `column` channel with an empty copy; None if it doesn't exist."""
    channel_id = getattr(world, column)
    old = guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
    if not isinstance(old, discord.TextChannel):
        return None
    new = await old.clone(reason=reason)
    await new.edit(position=old.position)
    await repos.update_world_column(await bot.db.guild(guild.id), world.name, column, str(new.id))
    bot.state.set_world(guild.id, dataclasses.replace(bot.state.guild(guild.id).worlds[world.name],
                                                      **{column: str(new.id)}))
    await old.delete(reason=reason)
    if INTROS.get(column):
        await new.send(embed=embeds.channel_intro(INTROS[column]))
    return new


class ConfirmClear(discord.ui.View):
    def __init__(self, world: str, target: str, owner_id: int):
        super().__init__(timeout=120)
        self.world, self.target, self.owner_id = world, target, owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id and has_manage_server(interaction.user)

    @discord.ui.button(label="Clear", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        self.stop()
        await interaction.response.edit_message(embed=embeds.response(":hourglass: Clearing..."), view=None)
        world = bot.state.guild(interaction.guild_id).worlds.get(self.world)
        if world is None:
            await interaction.edit_original_response(embed=embeds.error(f"**{self.world}** isn't set up here."))
            return
        cleared, missing = [], []
        try:
            for column in TARGETS[self.target]:
                world = bot.state.guild(interaction.guild_id).worlds[self.world]
                new = await clear_channel(bot, interaction.guild, world, column,
                                          f"/clear by {interaction.user}")
                (cleared if new else missing).append(new.mention if new else column.split("_")[0])
        except discord.Forbidden:
            await interaction.edit_original_response(embed=embeds.error(
                "I need **Manage Channels** to do that."))
            return
        if cleared:
            await adminlog.post(interaction.guild, bot.state.guild(interaction.guild_id).info,
                                f"{adminlog.user(interaction.user.name)} cleared {', '.join(cleared)} on "
                                f"**{self.world}**.", f"{embeds.WIKI_FILE}Hammer.gif")
        text = f"Cleared {', '.join(cleared)}." if cleared else "Nothing was cleared."
        if missing:
            text += f"\nMissing (run `/repair {self.world}`): {', '.join(missing)}."
        try:
            await interaction.edit_original_response(embed=embeds.ok(text))
        except discord.HTTPException:
            pass  # the reply lived in a channel that was just cleared

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(embed=embeds.response("Nothing was cleared."), view=None)


class ClearCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot

    @app_commands.command(name="clear", description="Delete every message in a world's deaths and/or levels channel")
    @app_commands.describe(channel="Which channel to empty", world="Only needed if you track more than one world")
    @app_commands.choices(channel=[app_commands.Choice(name="Deaths", value="deaths"),
                                   app_commands.Choice(name="Levels", value="levels"),
                                   app_commands.Choice(name="Both", value="both")])
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def clear(self, interaction: discord.Interaction, channel: app_commands.Choice[str],
                    world: str | None = None) -> None:
        if not has_manage_server(interaction.user):
            await interaction.response.send_message(
                embed=embeds.error("You need **Manage Server** to clear channels."), ephemeral=True)
            return
        worlds = self.bot.state.guild(interaction.guild_id).worlds
        if world is None and len(worlds) == 1:
            world = next(iter(worlds))
        picked = next((w for w in worlds if world and w.lower() == world.strip().lower()), None)
        if picked is None:
            await interaction.response.send_message(embed=embeds.error(
                "Pick one of your worlds: " + ", ".join(f"**{w}**" for w in sorted(worlds)) if worlds
                else "No worlds are set up here yet — run `/init` first."), ephemeral=True)
            return
        config = worlds[picked]
        names = []
        for column in TARGETS[channel.value]:
            cid = getattr(config, column)
            names.append(f"<#{cid}>" if cid.isdigit() and cid != "0" else column.split("_")[0])
        await interaction.response.send_message(
            embed=embeds.error(f"This deletes **every message** in {' and '.join(names)} on **{picked}**. "
                               "It can't be undone. Clear it?"),
            view=ConfirmClear(picked, channel.value, interaction.user.id), ephemeral=True)

    @clear.autocomplete("world")
    async def _world_autocomplete(self, interaction: discord.Interaction, current: str):
        names = sorted(self.bot.state.guild(interaction.guild_id).worlds)
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]


async def setup(bot: TibiaBot) -> None:
    await bot.add_cog(ClearCog(bot))
