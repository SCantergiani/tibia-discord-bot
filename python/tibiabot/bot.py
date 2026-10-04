from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from tibiabot import emojis
from tibiabot.config import Settings
from tibiabot.db import repos
from tibiabot.db.database import Database
from tibiabot.lists.service import ListService
from tibiabot.poller import PollerRegistry, WorldSnapshot
from tibiabot.state import BotState
from tibiabot.tibiadata.age_cache import CharacterAgeCache
from tibiabot.tibiadata.client import TibiaDataClient
from tibiabot.worlds import WorldList

log = logging.getLogger(__name__)

EXTENSIONS = ("tibiabot.cogs.setup", "tibiabot.cogs.lootsplit", "tibiabot.cogs.lists",
              "tibiabot.cogs.deaths", "tibiabot.cogs.settings")
LIST_REVIEW_INTERVAL = 30 * 60
CACHE_PRUNE_INTERVAL = 5 * 60


class TibiaBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        # Members intent is not needed; message content is not read.
        super().__init__(command_prefix=commands.when_mentioned, intents=intents,
                         allowed_mentions=discord.AllowedMentions(everyone=False, roles=True, users=True))
        self.settings = settings
        self.db = Database(settings)
        self.state = BotState()
        self.tibiadata = TibiaDataClient(settings.tibiadata_host, settings.tibiadata_max_in_flight)
        self.sheets = CharacterAgeCache(self.tibiadata.character, ttl=settings.character_cache_ttl,
                                        max_stale=settings.character_cache_max_stale)
        self.world_list = WorldList(self.tibiadata)
        self.pollers = PollerRegistry(self.tibiadata, self.sheets, settings.poll_interval)
        self.lists = ListService(self)
        self.pollers.listeners.append(self._log_snapshot)
        self.pollers.listeners.append(self.lists.on_snapshot)
        self._ready_once = False
        self._background: list[asyncio.Task] = []

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
        await self._load_guilds()
        await self.pollers.sync(self.state.tracked_worlds())
        self._background.append(asyncio.create_task(self._every(LIST_REVIEW_INTERVAL, self.lists.review_sweep),
                                                    name="list-review"))
        deaths_cog = self.get_cog("DeathsCog")
        if deaths_cog:
            self._background.append(asyncio.create_task(self._every(CACHE_PRUNE_INTERVAL, deaths_cog.prune),
                                                        name="death-cache-prune"))

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
