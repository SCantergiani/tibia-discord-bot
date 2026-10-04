"""The daily Bosses Due post (after server save) and `/bosses`.

Kill statistics are collected every 10 minutes until each tracked world's day is
filed; the post goes to each world's 📊 channel between 10:00 and 10:45 Berlin,
once per day, remembered in `worlds.statistics_posted`.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from tibiabot import bosses, creatures, embeds, emojis, killstats
from tibiabot.db import repos
from tibiabot.serversave import BERLIN, last_server_save

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

POST_FROM, POST_UNTIL = time(10, 0), time(10, 45)
PREDICTION_COLOR = 11563775


def game_day(now: datetime) -> date:
    """Today in Tibia: the day the last server save opened."""
    return last_server_save(now).date()


def closed_day(now: datetime) -> date:
    """The game day that ended at the last server save; what the daily post reports."""
    return game_day(now) - timedelta(days=1)


def _relative(when: datetime) -> str:
    return f"<t:{int(when.timestamp())}:R>"


def timing(chance: bosses.BossChance) -> str:
    if chance.days_since < chance.window_min:
        return f"opens {_relative(chance.opens_at)}"
    if chance.closes_at is not None:
        return (f"overdue since {_relative(chance.closes_at)}" if chance.days_since > chance.window_max
                else f"window closes {_relative(chance.closes_at)}")
    return f"overdue since {_relative(chance.opens_at)}"


def bosses_embed(world: str, predictions: list[bosses.BossPrediction], awaiting: int) -> discord.Embed:
    due = [p for p in predictions if p.best != bosses.NONE]
    icon = emojis.get("boss") or "👑"
    rows = []
    for p in due:
        dot = ":green_circle:" if p.best == bosses.HIGH else ":yellow_circle:"
        spawns = f" ×{len(p.leading)}" if len(p.leading) > 1 else ""
        rows.append(f"{dot} {creatures.boss_emoji(p.boss.name)}**{p.boss.name}**{spawns} · {timing(p.leading[0])}")
    if not rows:
        rows = [f"*No boss is inside a spawn window today, out of {len(predictions)} being tracked.*"
                if predictions else "*Not enough history yet to predict anything: a boss is predicted once the "
                                    "bot has seen it killed.*"]
    embed = discord.Embed(description=f"## {icon} Bosses Due on {world}\n" + "\n".join(rows), color=PREDICTION_COLOR)
    embed.description = embed.description[:4096]
    if awaiting:
        embed.set_footer(text=f"{awaiting} boss(es) not seen killed yet, so not predicted")
    return embed


class StatisticsCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot
        self.store = killstats.KillStatsStore(bot.db.cache)

    async def collect(self) -> None:
        await killstats.collect(self.bot.tibiadata, self.store, sorted(self.bot.state.tracked_worlds()))

    async def report(self, world: str, day: date) -> list[discord.Embed]:
        """The post after `day`'s server save: which bosses are due today."""
        sightings = await self.store.sightings(world)
        return [bosses_embed(world, bosses.predict_all(sightings, day + timedelta(days=1)),
                             bosses.awaiting_first_sighting(sightings))]

    async def post_due(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        if not POST_FROM <= now.astimezone(BERLIN).time() < POST_UNTIL:
            return
        day = closed_day(now)
        for guild_id, guild_state in list(self.bot.state.guilds.items()):
            guild = self.bot.get_guild(guild_id)
            for world in list(guild_state.worlds.values()):
                if guild is None or world.statistics_posted == day.isoformat():
                    continue
                if not await self.store.has_day(world.name, day):
                    continue  # kill statistics not filed yet; try again next minute
                channel = guild.get_channel(int(world.statistics_channel)) if world.statistics_channel.isdigit() \
                    else None
                if isinstance(channel, discord.TextChannel):
                    try:
                        await channel.send(embeds=await self.report(world.name, day), silent=True)
                    except discord.HTTPException as e:
                        log.warning("Could not post statistics in %s: %s", guild_id, e)
                        continue
                await repos.update_world_setting(await self.bot.db.guild(guild_id), world.name,
                                                 "statistics_posted", day.isoformat())
                self.bot.state.set_world(guild_id, dataclasses.replace(world, statistics_posted=day.isoformat()))

    @app_commands.command(name="bosses", description="Which rare bosses are due to spawn on your worlds")
    @app_commands.guild_only()
    async def bosses_command(self, interaction: discord.Interaction) -> None:
        worlds = sorted(self.bot.state.guild(interaction.guild_id).worlds)
        if not worlds:
            await interaction.response.send_message(
                embed=embeds.error("No worlds are set up here yet — run `/init` first."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        today = game_day(datetime.now(timezone.utc))
        out = []
        for world in worlds:
            sightings = await self.store.sightings(world)
            out.append(bosses_embed(world, bosses.predict_all(sightings, today),
                                    bosses.awaiting_first_sighting(sightings)))
        await interaction.followup.send(embeds=out[:10], ephemeral=True)


async def setup(bot: TibiaBot) -> None:
    await bot.add_cog(StatisticsCog(bot))
