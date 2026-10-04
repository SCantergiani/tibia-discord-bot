"""Keeps each server's 📈 online channel current: the list itself (edited in place),
the channel name's player count and the world category's ally/enemy counts."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from tibiabot import online
from tibiabot.db.repos import WorldConfig
from tibiabot.poller import WorldSnapshot

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

REFRESH_SECONDS = 60
# Discord allows two renames per channel per ten minutes; this stays under that.
RENAME_COOLDOWN = timedelta(minutes=7)
MASSLOG_QUIET_AFTER_START = 30 * 60
MASSLOG_ALERT_COOLDOWN = 15 * 60
MASSLOG_COLOR = 14397256
LIST_COLOR = 3092790


class OnlineCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot
        self._last_refresh: dict[int, float] = {}
        self._posted: dict[int, list[tuple[int, list[str]]]] = {}  # channel -> [(message id, descriptions)]
        self._locks: dict[int, asyncio.Lock] = {}
        self._started = time.time()
        self._last_alert: dict[tuple[int, str], float] = {}
        bot.pollers.listeners.append(self.on_snapshot)

    def cog_unload(self) -> None:
        if self.on_snapshot in self.bot.pollers.listeners:
            self.bot.pollers.listeners.remove(self.on_snapshot)

    async def on_snapshot(self, snapshot: WorldSnapshot) -> None:
        if snapshot.partial:
            return
        world_online = self.bot.online.setdefault(snapshot.world, online.WorldOnline())
        world_online.update(snapshot.online, snapshot.first_tick)
        now = time.monotonic()
        for guild_id, world in self.bot.state.guilds_tracking(snapshot.world):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            # Mass logs are checked on every poll; the list itself is redrawn less often.
            built = online.build(world_online, self.bot.lists.of(guild_id), world,
                                 self._guild_of(guild_id, world_online))
            if built.masslog:
                asyncio.create_task(self._masslog_alert(guild, world, built), name=f"masslog:{guild_id}")
            if now - self._last_refresh.get(guild_id, 0) < REFRESH_SECONDS:
                continue
            self._last_refresh[guild_id] = now
            asyncio.create_task(self._refresh(guild_id, world, world_online), name=f"online:{guild_id}")

    def _guild_of(self, guild_id: int, world_online: online.WorldOnline) -> dict[str, str]:
        """Each online player's guild: from their sheet if known, else a listed guild's roster."""
        lists = self.bot.lists.of(guild_id)
        roster = {member: guild for guild, members in lists.rosters.items() for member in members}
        result = {}
        for name in world_online.players:
            sheet = self.bot.sheets.peek(name)
            guild = sheet.guild_name if sheet and sheet.guild_name else roster.get(name.lower(), "")
            if guild and not sheet:
                guild = guild.title()
            result[name] = guild or ""
        return result

    async def _refresh(self, guild_id: int, world: WorldConfig, world_online: online.WorldOnline) -> None:
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(int(world.allies_channel)) if guild and world.allies_channel.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            return
        lock = self._locks.setdefault(channel.id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            try:
                built = online.build(world_online, self.bot.lists.of(guild_id), world,
                                     self._guild_of(guild_id, world_online))
                lines = built.lines or ["*Nobody is online right now.*"]
                await self._post(channel, online.pack_messages(lines))
                await self._rename(channel, f"{online.base_name(channel.name, 'online')}-{built.total}", world.name)
                category = guild.get_channel(int(world.category)) if world.category.isdigit() else None
                if isinstance(category, discord.CategoryChannel):
                    masslog = built.masslog and time.time() - self._started > MASSLOG_QUIET_AFTER_START
                    name = online.category_name(world.name, built.allies, built.enemies) + ("⚡" if masslog else "")
                    await self._rename(category, name, world.name)
            except discord.HTTPException as e:
                log.warning("Online list update failed in %s: %s", guild_id, e)
            except Exception:
                log.exception("Online list update failed in %s", guild_id)

    # --- mass log -------------------------------------------------------------

    async def _masslog_alert(self, guild: discord.Guild, world: WorldConfig, built: online.OnlineList) -> None:
        """Many enemies just logged in: ping whoever this world's setting names."""
        mode = online.masslog_mode(world)
        key = (guild.id, world.name)
        if mode == "off" or time.monotonic() - self._last_alert.get(key, -MASSLOG_ALERT_COOLDOWN) \
                < MASSLOG_ALERT_COOLDOWN:
            return
        channel = guild.get_channel(int(world.deaths_channel)) if world.deaths_channel.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            return
        self._last_alert[key] = time.monotonic()
        role = guild.get_role(int(world.masslog_role)) if mode == "role" else None
        content = "@everyone" if mode == "everyone" else role.mention if role else None
        who = "\n".join(built.fresh_enemies[:25])
        more = f"\n*…and {len(built.fresh_enemies) - 25} more*" if len(built.fresh_enemies) > 25 else ""
        embed = discord.Embed(
            title=f"⚡ Mass log on {world.name}", color=MASSLOG_COLOR,
            description=(f"**{len(built.fresh_enemies)}** enemies logged in within the last 15 minutes "
                         f"(**{built.enemies}** online).\n\n{who}{more}")[:4096])
        try:
            await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions(
                everyone=mode == "everyone", roles=[role] if role else []))
        except discord.HTTPException as e:
            log.warning("Could not post a mass log alert in %s: %s", guild.id, e)

    # --- the messages --------------------------------------------------------

    async def _existing(self, channel: discord.TextChannel) -> list[tuple[int, list[str]]]:
        """Our messages in the channel, oldest first: read once, then remembered."""
        if channel.id not in self._posted:
            mine = [m async for m in channel.history(limit=50) if m.author.id == self.bot.user.id]
            self._posted[channel.id] = [(m.id, [e.description or "" for e in m.embeds]) for m in reversed(mine)]
        return self._posted[channel.id]

    @staticmethod
    def _embeds(descriptions: list[str], last_message: bool) -> list[discord.Embed]:
        out = []
        for i, description in enumerate(descriptions):
            embed = discord.Embed(description=description, color=LIST_COLOR)
            if last_message and i == len(descriptions) - 1:
                embed.set_footer(text="Last updated")
                embed.timestamp = datetime.now(timezone.utc)
            out.append(embed)
        return out

    async def _post(self, channel: discord.TextChannel, messages: list[list[str]]) -> None:
        existing = await self._existing(channel)
        posted: list[tuple[int, list[str]]] = []
        last = len(messages) - 1
        for i, descriptions in enumerate(messages):
            embeds = self._embeds(descriptions, i == last)
            if i < len(existing):
                message_id, before = existing[i]
                # The last message always changes (its footer time); the others only when the text did.
                if before != descriptions or i == last:
                    try:
                        await channel.get_partial_message(message_id).edit(embeds=embeds)
                    except discord.NotFound:
                        message_id = (await channel.send(embeds=embeds, silent=True)).id
                posted.append((message_id, descriptions))
            else:
                message = await channel.send(embeds=embeds, silent=True)
                posted.append((message.id, descriptions))
        for message_id, _ in existing[len(messages):]:
            try:
                await channel.get_partial_message(message_id).delete()
            except discord.NotFound:
                pass
        self._posted[channel.id] = posted

    # --- renames -------------------------------------------------------------

    async def _rename(self, channel: discord.abc.GuildChannel, name: str, world: str) -> None:
        if channel.name == name:
            return
        cache = self.bot.db.cache
        last = await cache.fetchval("SELECT last_rename FROM rename_cooldowns WHERE channel_id = $1", str(channel.id))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if last and now - last < RENAME_COOLDOWN:
            return
        await cache.execute(
            "INSERT INTO rename_cooldowns (channel_id, world, last_rename) VALUES ($1, $2, $3) "
            "ON CONFLICT (channel_id) DO UPDATE SET last_rename = EXCLUDED.last_rename", str(channel.id), world, now)
        await channel.edit(name=name)


async def setup(bot: TibiaBot) -> None:
    await bot.add_cog(OnlineCog(bot))
