"""Posts deaths and level-ups to every server tracking the polled world."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from tibiabot import deaths, emojis, serversave
from tibiabot.db.repos import NONE_ID, WorldConfig
from tibiabot.lists.embeds import pack
from tibiabot.poller import WorldSnapshot
from tibiabot.tibiadata.client import TibiaDataError

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

PING_COOLDOWN = 30 * 60
KILLER_LOOKUP_CAP = 40
KILLER_LOOKUP_CONCURRENCY = 6
KILLER_LOOKUP_TIMEOUT = 10
LEVEL_MESSAGE_LIMIT = 1900


def _channel(guild: discord.Guild, channel_id: str) -> discord.TextChannel | None:
    channel = guild.get_channel(int(channel_id)) if channel_id and channel_id.isdigit() else None
    return channel if isinstance(channel, discord.TextChannel) else None


def _role(guild: discord.Guild, role_id: str) -> discord.Role | None:
    return guild.get_role(int(role_id)) if role_id and role_id.isdigit() and role_id != NONE_ID else None


class DeathsCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot
        self.death_detector = deaths.DeathDetector(bot.db.cache)
        self.level_detector = deaths.LevelDetector(bot.db.cache)
        self._last_ping: dict[int, float] = {}
        bot.pollers.listeners.append(self.on_snapshot)

    def cog_unload(self) -> None:
        if self.on_snapshot in self.bot.pollers.listeners:
            self.bot.pollers.listeners.remove(self.on_snapshot)

    async def prune(self) -> None:
        await self.death_detector.prune()
        await self.level_detector.prune()

    def _can_ping(self, channel_id: int) -> bool:
        """At most one role ping per channel every 30 minutes."""
        now = time.monotonic()
        if now - self._last_ping.get(channel_id, -PING_COOLDOWN) < PING_COOLDOWN:
            return False
        self._last_ping[channel_id] = now
        return True

    async def on_snapshot(self, snapshot: WorldSnapshot) -> None:
        found = await self.death_detector.detect(snapshot)
        ups = await self.level_detector.detect(snapshot)
        world_online = self.bot.online.get(snapshot.world)
        if world_online:
            for up in ups:
                world_online.set_flag(up.character.name, emojis.get("levelup"))
        if snapshot.first_tick:
            # Tibia only updates a sheet's level on logout, so the first poll sees
            # every level gained this session at once. Remember them, post none.
            ups = []
        if not snapshot.first_tick:  # the first poll also finds deaths from before the bot started
            now = datetime.now(timezone.utc)
            for character, death in found:
                side = self.bot._listed_side(snapshot.world, character.name, character) or "neutral"
                self.bot.stats.record_death(side, (now - death.time).total_seconds())
        if not found and not ups:
            return
        killer_levels = await self._killer_levels(snapshot, found) if found else {}
        for guild_id, world in self.bot.state.guilds_tracking(snapshot.world):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            try:
                if found:
                    await self._post_deaths(guild, world, found, killer_levels)
                if ups:
                    await self._post_levels(guild, world, ups)
            except Exception:
                log.exception("Posting to guild %s for %s failed", guild_id, snapshot.world)

    # --- killer levels -------------------------------------------------------

    async def _killer_levels(self, snapshot: WorldSnapshot, found) -> dict[str, int]:
        """Online list first, then any sheet already cached, then a bounded lookup."""
        levels = deaths.online_levels(snapshot)
        wanted = [n for n in deaths.killer_names(found) if n.lower() not in levels]
        missing = []
        for name in wanted:
            cached = self.bot.sheets.peek(name)
            if cached:
                levels[name.lower()] = cached.level
            else:
                missing.append(name)
        gate = asyncio.Semaphore(KILLER_LOOKUP_CONCURRENCY)

        async def one(name: str) -> None:
            async with gate:
                try:
                    levels[name.lower()] = (await self.bot.sheets.get(name)).level
                except TibiaDataError:
                    pass

        if missing:
            try:
                await asyncio.wait_for(asyncio.gather(*(one(n) for n in missing[:KILLER_LOOKUP_CAP])),
                                       KILLER_LOOKUP_TIMEOUT)
            except asyncio.TimeoutError:
                log.debug("Killer level lookups timed out; posting without some levels")
        return levels

    # --- deaths --------------------------------------------------------------

    async def _custom_sort(self, guild_id: int) -> set[tuple[str, str]]:
        pool = await self.bot.db.guild(guild_id)
        rows = await pool.fetch("SELECT entity, name FROM online_list_categories")
        return {(r["entity"], r["name"].lower()) for r in rows}

    async def _post_deaths(self, guild: discord.Guild, world: WorldConfig, found, killer_levels) -> None:
        channel = _channel(guild, world.deaths_channel)
        if channel is None:
            return
        lists = self.bot.lists.of(guild.id)
        custom_sort = await self._custom_sort(guild.id)
        for character, death in found:
            post = deaths.build_death(character, death, lists, world, killer_levels, custom_sort)
            if not post.visible(world):
                continue
            message = await self._send_death(guild, channel, world, post)
            if post.frag_killers and post.relation and (post.relation.ally or post.relation.enemy):
                await self._record_frags(guild.id, world.name, post, message)

    async def _send_death(self, guild: discord.Guild, channel: discord.TextChannel, world: WorldConfig,
                          post: deaths.DeathPost) -> discord.Message | None:
        embed = discord.Embed(title=post.title, url=post.url, description=post.description, color=post.color)
        embed.set_thumbnail(url=post.thumbnail)
        if post.side_label:
            embed.set_author(name=post.side_label)
        ping: discord.Role | None = None
        silent = False
        if post.poke == "nemesis":
            role = _role(guild, world.nemesis_role)
            ping = role if role and self._can_ping(channel.id) else None
        elif post.level < world.deaths_min:
            return None
        elif post.poke == "allypk":
            role = _role(guild, world.allypk_role)
            ping = role if role and self._can_ping(channel.id) else None
        elif post.poke == "fullbless":
            embed.description += deaths.exiva_blocks([post.victim])
            role = _role(guild, world.fullbless_role)
            ping = role if role and post.level >= world.fullbless_level else None
        elif not (post.relation and (post.relation.ally or post.relation.enemy)):
            silent = True  # only neutral deaths arrive without a notification
        try:
            return await channel.send(content=ping.mention if ping else None, embed=embed, silent=silent,
                                      allowed_mentions=discord.AllowedMentions(roles=[ping] if ping else []))
        except discord.HTTPException as e:
            log.warning("Could not post a death in %s: %s", guild.id, e)
            return None

    async def _record_frags(self, guild_id: int, world: str, post: deaths.DeathPost,
                            message: discord.Message | None) -> None:
        side = "enemy" if post.relation.enemy else "ally"
        occurred = post.time.astimezone(timezone.utc).replace(tzinfo=None)
        pool = await self.bot.db.guild(guild_id)
        await pool.executemany(
            "INSERT INTO frag_event (world, save_day, killer, victim, victim_level, victim_side, occurred_at, "
            "death_message_id) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING",
            [(world, serversave.save_day(post.time), killer, post.victim, post.level, side, occurred,
              str(message.id) if message else "") for killer in post.frag_killers])

    # --- levels --------------------------------------------------------------

    async def _post_levels(self, guild: discord.Guild, world: WorldConfig, ups) -> None:
        channel = _channel(guild, world.levels_channel)
        if channel is None:
            return
        lists = self.bot.lists.of(guild.id)
        lines = []
        for up in ups:
            line, rel = deaths.level_line(up, lists)
            if deaths.level_visible(rel, up.level, world):
                lines.append(line)
        for chunk in pack(lines, LEVEL_MESSAGE_LIMIT) if lines else []:
            try:
                await channel.send(chunk, silent=True, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as e:
                log.warning("Could not post level-ups in %s: %s", guild.id, e)


async def setup(bot: TibiaBot) -> None:
    await bot.add_cog(DeathsCog(bot))
