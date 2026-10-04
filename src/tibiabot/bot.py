from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from tibiabot import emojis
from tibiabot.commands_guide import ensure_guide
from tibiabot.config import Settings
from tibiabot.db import repos
from tibiabot.db.database import Database
from tibiabot.lists.service import ListService
from tibiabot.online import WorldOnline
from tibiabot.poller import FastLane, PollerRegistry, WorldSnapshot
from tibiabot.ratelimit import AdaptiveRate
from tibiabot.state import BotState
from tibiabot.tibiadata.age_cache import CharacterAgeCache
from tibiabot.tibiadata.client import TibiaDataClient
from tibiabot.worlds import WorldList

log = logging.getLogger(__name__)

EXTENSIONS = ("tibiabot.cogs.setup", "tibiabot.cogs.lootsplit", "tibiabot.cogs.lists",
              "tibiabot.cogs.deaths", "tibiabot.cogs.settings", "tibiabot.cogs.online",
              "tibiabot.cogs.statistics", "tibiabot.cogs.watchdog",
              "tibiabot.cogs.hunt", "tibiabot.cogs.clear")
LIST_REVIEW_INTERVAL = 30 * 60
CACHE_PRUNE_INTERVAL = 5 * 60
ROSTER_REFRESH_INTERVAL = 10 * 60
KILL_STATS_INTERVAL = 10 * 60


class TibiaBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        # Members intent is not needed; message content is not read.
        # No message cache: the bot never reads past messages from memory (it fetches
        # its own online-list messages once), and the default 1,000 cost RAM.
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, max_messages=None,
                         allowed_mentions=discord.AllowedMentions(everyone=False, roles=True, users=True))
        self.settings = settings
        self.db = Database(settings)
        self.state = BotState()
        self.tibiadata = TibiaDataClient(settings.tibiadata_host, settings.tibiadata_max_in_flight)
        self.sheets = CharacterAgeCache(self.tibiadata.character, ttl=settings.character_cache_ttl,
                                        max_stale=settings.character_cache_max_stale)
        self.world_list = WorldList(self.tibiadata)
        # One rate for everything sent to tibia.com: it counts per IP.
        self.rate = (AdaptiveRate(settings.fast_poll_max_per_second, settings.fast_poll_ceiling)
                     if settings.fresh_tibiadata and settings.fast_poll_seconds > 0 else None)
        if self.rate:
            self.tibiadata.on_pushback = self.rate.on_pushback
        fast = (FastLane(settings.fast_poll_seconds, settings.fast_poll_max_per_second,
                         ally_interval=settings.ally_poll_seconds, limiter=self.rate)
                if self.rate else None)
        self.pollers = PollerRegistry(self.tibiadata, self.sheets, settings.poll_interval,
                                      self._listed_side if settings.fresh_tibiadata else None, fast,
                                      relevant=self._listed_side, wants_neutrals=self._wants_neutrals)
        self.lists = ListService(self)
        self.online: dict[str, WorldOnline] = {}  # world -> who is online, see cogs/online.py
        self.pollers.listeners.append(self._log_snapshot)
        self.pollers.listeners.append(self.lists.on_snapshot)
        self._ready_once = False
        self._background: list[asyncio.Task] = []

    def _listed_side(self, world: str, name: str, sheet) -> str | None:
        """"enemy" or "ally" for any server tracking `world` (enemy wins: it is checked
        more often), None for everyone else."""
        lower = name.lower()
        guild = (sheet.guild_name or "").lower() if sheet else ""
        side = None
        for guild_id, _ in self.state.guilds_tracking(world):
            lists = self.lists.of(guild_id)
            if lower in lists.hunted_players or (guild and guild in lists.hunted_guilds) \
                    or any(lower in lists.rosters.get(g, ()) for g in lists.hunted_guilds):
                return "enemy"
            if lower in lists.allied_players or (guild and guild in lists.allied_guilds) \
                    or any(lower in lists.rosters.get(g, ()) for g in lists.allied_guilds):
                side = "ally"
        return side

    def _wants_neutrals(self, world: str) -> bool:
        """False only when every server tracking `world` hides neutral deaths and levels."""
        return any(w.show_neutral_deaths != "false" or w.show_neutral_levels != "false"
                   for _, w in self.state.guilds_tracking(world))

    @property
    def owner_user_id(self) -> int | None:
        """BOT_OWNER_ID, else the application owner Discord reports. Never hardcoded."""
        if self.settings.bot_owner_id.isdigit():
            return int(self.settings.bot_owner_id)
        return self.owner_id

    async def setup_hook(self) -> None:
        await self.db.start()
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        if self.settings.dev_guild_id.isdigit():
            guild = discord.Object(id=int(self.settings.dev_guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), guild.id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (may take up to an hour to appear)", len(synced))
        try:
            await emojis.sync(self, self.settings.emoji_dir)
        except discord.HTTPException as e:
            log.warning("Emoji sync failed, falling back to Unicode: %s", e)

    async def on_ready(self) -> None:
        if self._ready_once:
            return
        self._ready_once = True
        await self.is_owner(self.user)  # populates owner_id from application info
        log.info("Logged in as %s (%s), owner %s, in %d guilds",
                 self.user, self.user.id, self.owner_user_id, len(self.guilds))
        log.info("TibiaData: %s (%s), polling every %ss", self.settings.tibiadata_host,
                 (f"self-hosted, allies and enemies re-checked every {self.settings.fast_poll_seconds:g}s at "
                  f"{self.settings.fast_poll_max_per_second:g} requests/s, adapting up to "
                  f"{self.settings.fast_poll_ceiling:g}") if self.settings.fresh_tibiadata
                 else "public, character pages up to 5 minutes old", self.settings.poll_interval)
        await self._load_guilds()
        if not self.settings.dev_guild_id.isdigit():
            await self._clear_dev_commands()
        await self._refresh_guides()
        await self.pollers.sync(self.state.tracked_worlds())
        self._background.append(asyncio.create_task(self._every(LIST_REVIEW_INTERVAL, self.lists.review_sweep),
                                                    name="list-review"))
        self._background.append(asyncio.create_task(self._every(ROSTER_REFRESH_INTERVAL, self.lists.refresh_rosters),
                                                    name="roster-refresh"))
        stats_cog = self.get_cog("StatisticsCog")
        if stats_cog:
            self._background.append(asyncio.create_task(self._every(KILL_STATS_INTERVAL, stats_cog.collect),
                                                        name="kill-statistics"))
            self._background.append(asyncio.create_task(self._every(60, stats_cog.post_due), name="statistics-post"))
            asyncio.create_task(stats_cog.collect(), name="kill-statistics-first")
        deaths_cog = self.get_cog("DeathsCog")
        if deaths_cog:
            self._background.append(asyncio.create_task(self._every(CACHE_PRUNE_INTERVAL, deaths_cog.prune),
                                                        name="death-cache-prune"))

    async def _refresh_guides(self) -> None:
        """Bring every server's 📖 commands channel up to date with this version's commands."""
        for guild in self.guilds:
            info = self.state.guild(guild.id).info
            category = guild.get_channel(int(info.admin_category)) if info and info.admin_category.isdigit() else None
            if isinstance(category, discord.CategoryChannel):
                try:
                    await ensure_guide(guild, category)
                except discord.HTTPException as e:
                    log.warning("Could not update the commands channel in %s: %s", guild.name, e)

    async def _clear_dev_commands(self) -> None:
        """With global commands, drop any server-only copies left from testing with
        DEV_GUILD_ID, which would otherwise show every command twice there."""
        for guild in self.guilds:
            try:
                if await self.tree.fetch_commands(guild=guild):
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                    log.info("Removed test-only command copies from %s", guild.name)
            except discord.HTTPException as e:
                log.warning("Could not check commands in %s: %s", guild.name, e)

    async def _load_guilds(self) -> None:
        for guild in self.guilds:
            if not await self.db.guild_exists(guild.id):
                continue
            pool = await self.db.init_guild(guild.id)
            state = self.state.guild(guild.id)
            state.info = await repos.get_discord_info(pool)
            state.worlds = {w.name: w for w in await repos.list_worlds(pool)}
            await self.lists.load(guild.id)
        tracked = {gid: sorted(g.worlds) for gid, g in self.state.guilds.items() if g.worlds}
        log.info("Loaded config: %s", tracked or "no worlds tracked yet")

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        log.info("Removed from guild %s (%s); dropping its database", guild.name, guild.id)
        self.state.forget_guild(guild.id)
        self.lists.forget(guild.id)
        await self.pollers.sync(self.state.tracked_worlds())
        await self.db.drop_guild(guild.id)

    async def _log_snapshot(self, snapshot: WorldSnapshot) -> None:
        if snapshot.partial:
            return
        log.info("%s: %d online, %d sheets (%d cached), %d recently offline",
                 snapshot.world, len(snapshot.online), len(snapshot.characters), len(self.sheets),
                 len(snapshot.recently_offline))

    @staticmethod
    async def _every(seconds: float, job) -> None:
        while True:
            await asyncio.sleep(seconds)
            try:
                await job()
            except Exception:
                log.exception("Background job %s failed", getattr(job, "__name__", job))

    async def close(self) -> None:
        for task in self._background:
            task.cancel()
        await self.pollers.stop_all()
        await self.tibiadata.close()
        await self.db.close()
        await super().close()
