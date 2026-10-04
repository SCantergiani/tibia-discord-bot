"""Keeps each world's 🤍 allies and ⚔️ enemies channels current: the lists (edited in
place), the count in each channel's name, and mass log alerts in the enemies channel."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from tibiabot import online
from tibiabot.db import repos
from tibiabot.db.repos import WorldConfig
from tibiabot.poller import WorldSnapshot

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

REFRESH_SECONDS = 60
# Discord allows two renames per channel per ten minutes: one every five, with a little
# margin so a rename never lands on the limit and gets held back by Discord.
RENAME_COOLDOWN = timedelta(minutes=5, seconds=5)
MASSLOG_QUIET_AFTER_START = 30 * 60
MASSLOG_COLOR = 14397256
MASSLOG_ALERT_LIFETIME = 20 * 60  # an alert is deleted this long after it was posted
LIST_COLOR = 3092790


class OnlineCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot
        self._last_refresh: dict[int, float] = {}
        self._posted: dict[int, list[tuple[int, list[str]]]] = {}  # channel -> [(message id, descriptions)]
        self._locks: dict[int, asyncio.Lock] = {}
        self._wanted_name: dict[int, str] = {}
        self._renaming: dict[int, asyncio.Task] = {}
        self._create_tried: set[tuple[int, str]] = set()
        self._swept: set[int] = set()
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
            built = self._build(guild_id, world, world_online)
            if built.masslog:
                asyncio.create_task(self._masslog_alert(guild, world, built), name=f"masslog:{guild_id}")
            if now - self._last_refresh.get(guild_id, 0) < REFRESH_SECONDS:
                continue
            self._last_refresh[guild_id] = now
            asyncio.create_task(self._refresh(guild_id, world, world_online), name=f"online:{guild_id}")

    def _build(self, guild_id: int, world: WorldConfig, world_online: online.WorldOnline) -> online.OnlineList:
        settings = self.bot.settings
        return online.build(world_online, self.bot.lists.of(guild_id), world, self._guild_of(guild_id, world_online),
                            masslog_window=settings.masslog_minutes * 60, masslog_min=settings.masslog_min_enemies)

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

    @staticmethod
    def _text_channel(guild: discord.Guild, channel_id: str) -> discord.TextChannel | None:
        channel = guild.get_channel(int(channel_id)) if channel_id.isdigit() and channel_id != "0" else None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _enemies_channel(self, guild: discord.Guild, world: WorldConfig,
                               allies: discord.TextChannel) -> discord.TextChannel | None:
        """The world's enemies channel. A world set up before the lists were split gets
        one next to its allies channel, with the same permissions (tried once per run)."""
        channel = self._text_channel(guild, world.enemies_channel)
        if channel or (guild.id, world.name) in self._create_tried:
            return channel
        self._create_tried.add((guild.id, world.name))
        try:
            channel = await guild.create_text_channel(
                online.ENEMIES_CHANNEL, category=allies.category, overwrites=allies.overwrites,
                reason="Allies and enemies online lists split")
            pool = await self.bot.db.guild(guild.id)
            await repos.update_world_column(pool, world.name, "enemies_channel", str(channel.id))
        except discord.HTTPException as e:
            log.warning("Could not create the enemies channel for %s in %s: %s", world.name, guild.id, e)
            return None
        self.bot.state.set_world(guild.id, dataclasses.replace(world, enemies_channel=str(channel.id)))
        log.info("Created the enemies channel for %s in %s", world.name, guild.id)
        return channel

    async def _refresh(self, guild_id: int, world: WorldConfig, world_online: online.WorldOnline) -> None:
        guild = self.bot.get_guild(guild_id)
        allies = self._text_channel(guild, world.allies_channel) if guild else None
        if allies is None:
            return
        lock = self._locks.setdefault(allies.id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            try:
                enemies = await self._enemies_channel(guild, world, allies)
                deaths = self._text_channel(guild, world.deaths_channel)
                if enemies and deaths and deaths.id not in self._swept:
                    await self._sweep_old_alerts(deaths)
                built = self._build(guild_id, world, world_online)
                masslog = built.masslog and time.time() - self._started > MASSLOG_QUIET_AFTER_START
                if enemies is None:  # couldn't make one: both sides share the allies channel
                    await self._post(allies, online.pack_messages(
                        built.lines or ["*No allies or enemies are online right now.*"]))
                    self._rename_soon(allies, online.channel_name(self._base(allies, online.ALLIES_CHANNEL),
                                                                  built.allies), world.name)
                    return
                await self._order(enemies, allies)
                await self._post(allies, online.pack_messages(
                    built.ally_lines or ["*No allies are online right now.*"]))
                await self._post(enemies, online.pack_messages(
                    built.enemy_lines or ["*No enemies are online right now.*"]))
                self._rename_soon(allies, online.channel_name(self._base(allies, online.ALLIES_CHANNEL),
                                                              built.allies), world.name)
                self._rename_soon(enemies, online.channel_name(self._base(enemies, online.ENEMIES_CHANNEL),
                                                               built.enemies, masslog), world.name)
            except discord.HTTPException as e:
                log.warning("Online list update failed in %s: %s", guild_id, e)
            except Exception:
                log.exception("Online list update failed in %s", guild_id)

    @staticmethod
    async def _order(enemies: discord.TextChannel, allies: discord.TextChannel) -> None:
        """Enemies first in the world's category, allies second, then the rest."""
        category = allies.category
        if category is None or enemies.category_id != category.id or category.text_channels[:2] == [enemies, allies]:
            return
        try:
            await enemies.move(beginning=True, sync_permissions=False, reason="Enemies first, then allies")
            await allies.move(after=enemies, sync_permissions=False, reason="Enemies first, then allies")
        except discord.HTTPException as e:
            log.warning("Could not reorder the online channels in %s: %s", category.guild.id, e)

    @staticmethod
    def _base(channel: discord.TextChannel, default: str) -> str:
        """The channel's name without the count; the old shared list becomes the allies list."""
        base = online.base_name(channel.name, default)
        return default if base == online.OLD_ONLINE_CHANNEL else base

    # --- mass log -------------------------------------------------------------

    async def _masslog_alert(self, guild: discord.Guild, world: WorldConfig, built: online.OnlineList) -> None:
        """Many enemies just logged in: ping whoever this world's setting names, in the
        enemies channel (the deaths channel until the world has one)."""
        mode = online.masslog_mode(world)
        key = (guild.id, world.name)
        # One alert per wave: the next needs a fresh window's worth of logins.
        window = self.bot.settings.masslog_minutes * 60
        if mode == "off" or time.monotonic() - self._last_alert.get(key, -window) < window:
            return
        world = self.bot.state.guild(guild.id).worlds.get(world.name, world)  # may have just got its channel
        channel = self._text_channel(guild, world.enemies_channel) or self._text_channel(guild, world.deaths_channel)
        if channel is None:
            return
        self._last_alert[key] = time.monotonic()
        if mode == "members":
            info = self.bot.state.guild(guild.id).info
            member_role = info.member_role if info else ""
            role = guild.get_role(int(member_role)) if member_role and member_role.isdigit() else None
        else:
            role = guild.get_role(int(world.masslog_role)) if mode == "role" else None
        content = "@everyone" if mode == "everyone" else role.mention if role else None
        who = "\n".join(built.fresh_enemies[:25])
        more = f"\n*…and {len(built.fresh_enemies) - 25} more*" if len(built.fresh_enemies) > 25 else ""
        embed = discord.Embed(
            title=f"⚡ Mass log on {world.name}", color=MASSLOG_COLOR,
            description=(f"**{len(built.fresh_enemies)}** enemies logged in within the last "
                         f"{self.bot.settings.masslog_minutes:g} minutes "
                         f"(**{built.enemies}** online).\n\n{who}{more}")[:4096])
        try:
            message = await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions(
                everyone=mode == "everyone", roles=[role] if role else []))
            self._expire(message, MASSLOG_ALERT_LIFETIME)
        except discord.HTTPException as e:
            log.warning("Could not post a mass log alert in %s: %s", guild.id, e)

    # --- the messages --------------------------------------------------------

    async def _existing(self, channel: discord.TextChannel) -> list[tuple[int, list[str]]]:
        """Our messages in the channel, oldest first: read once, then remembered."""
        if channel.id not in self._posted:
            ours = [m async for m in channel.history(limit=50) if m.author.id == self.bot.user.id and m.embeds]
            # Mass log alerts left from before a restart: due to go, or gone already.
            now = datetime.now(timezone.utc)
            for m in ours:
                if any(e.color and e.color.value == MASSLOG_COLOR for e in m.embeds):
                    self._expire(m, MASSLOG_ALERT_LIFETIME - (now - m.created_at).total_seconds())
            mine = [m for m in ours if all(e.color and e.color.value == LIST_COLOR for e in m.embeds)]
            self._posted[channel.id] = [(m.id, [e.description or "" for e in m.embeds]) for m in reversed(mine)]
        return self._posted[channel.id]

    async def _sweep_old_alerts(self, channel: discord.TextChannel) -> None:
        """Mass log alerts used to go to the deaths channel: expire those too (once a run)."""
        self._swept.add(channel.id)
        now = datetime.now(timezone.utc)
        async for m in channel.history(limit=100):
            if m.author.id == self.bot.user.id and any(e.color and e.color.value == MASSLOG_COLOR for e in m.embeds):
                self._expire(m, MASSLOG_ALERT_LIFETIME - (now - m.created_at).total_seconds())

    def _expire(self, message: discord.Message, after: float, sleep=asyncio.sleep) -> asyncio.Task:
        async def run() -> None:
            if after > 0:
                await sleep(after)
            try:
                await message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException as e:
                log.warning("Could not delete mass log alert %s: %s", message.id, e)
        return asyncio.create_task(run(), name=f"expire:{message.id}")

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

    def _rename_soon(self, channel: discord.abc.GuildChannel, name: str, world: str) -> None:
        """Rename in the background, as soon as Discord's limit allows, to whatever name is
        wanted by then: the lists never wait on a rename, and counts never lag more than
        the limit forces."""
        self._wanted_name[channel.id] = name
        pending = self._renaming.get(channel.id)
        if pending is None or pending.done():
            self._renaming[channel.id] = asyncio.create_task(self._rename(channel, world),
                                                             name=f"rename:{channel.id}")

    async def _rename(self, channel: discord.abc.GuildChannel, world: str,
                      sleep=asyncio.sleep) -> None:
        cache = self.bot.db.cache
        done = channel.name
        try:
            while (name := self._wanted_name.get(channel.id)) and name != done:
                last = await cache.fetchval("SELECT last_rename FROM rename_cooldowns WHERE channel_id = $1",
                                            str(channel.id))
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                if last and now - last < RENAME_COOLDOWN:
                    await sleep((RENAME_COOLDOWN - (now - last)).total_seconds())
                    continue
                await cache.execute(
                    "INSERT INTO rename_cooldowns (channel_id, world, last_rename) VALUES ($1, $2, $3) "
                    "ON CONFLICT (channel_id) DO UPDATE SET last_rename = EXCLUDED.last_rename",
                    str(channel.id), world, now)
                await channel.edit(name=name)
                done = name
        except discord.HTTPException as e:
            log.warning("Could not rename %s: %s", channel.id, e)


async def setup(bot: TibiaBot) -> None:
    await bot.add_cog(OnlineCog(bot))
