"""Connection pools for the three kinds of database the bot uses.

- `postgres`: admin connection, only to create or drop the others.
- `bot_cache`: shared across every guild.
- `_<guildId>`: one per Discord server, created by `/setup`.
"""

from __future__ import annotations

import asyncio
import logging
from importlib import resources

import asyncpg

from tibiabot.config import Settings

log = logging.getLogger(__name__)

CACHE_DB = "bot_cache"


def guild_db_name(guild_id: int | str) -> str:
    """A database name can't be a bound parameter, so only digits get through."""
    text = str(guild_id)
    if not text.isdigit():
        raise ValueError(f"refusing unsafe guild database name: {text!r}")
    return f"_{text}"


def _ddl(name: str) -> str:
    return resources.files("tibiabot.db").joinpath(name).read_text(encoding="utf-8")


class Database:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._cache: asyncpg.Pool | None = None
        self._guilds: dict[str, asyncpg.Pool] = {}
        self._lock = asyncio.Lock()

    async def _connect_admin(self) -> asyncpg.Connection:
        return await self._connect("postgres")

    async def _connect(self, database: str) -> asyncpg.Connection:
        s = self._settings
        return await asyncpg.connect(host=s.postgres_host, port=s.postgres_port, user=s.postgres_user,
                                     password=s.postgres_password, database=database)

    async def _pool(self, database: str) -> asyncpg.Pool:
        s = self._settings
        return await asyncpg.create_pool(host=s.postgres_host, port=s.postgres_port, user=s.postgres_user,
                                         password=s.postgres_password, database=database,
                                         min_size=0, max_size=3)

    async def _ensure_database(self, name: str) -> bool:
        """Create `name` if missing. True when it was created now."""
        admin = await self._connect_admin()
        try:
            if await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
                return False
            await admin.execute(f'CREATE DATABASE "{name}"')
            log.info("Created database %s", name)
            return True
        except asyncpg.DuplicateDatabaseError:
            return False
        finally:
            await admin.close()

    async def start(self) -> None:
        await self._ensure_database(CACHE_DB)
        self._cache = await self._pool(CACHE_DB)
        async with self._cache.acquire() as conn:
            await conn.execute(_ddl("cache.sql"))

    async def close(self) -> None:
        pools = [p for p in [self._cache, *self._guilds.values()] if p]
        await asyncio.gather(*(p.close() for p in pools), return_exceptions=True)
        self._guilds.clear()

    @property
    def cache(self) -> asyncpg.Pool:
        if self._cache is None:
            raise RuntimeError("Database.start() has not run")
        return self._cache

    async def guild_exists(self, guild_id: int | str) -> bool:
        admin = await self._connect_admin()
        try:
            return bool(await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1",
                                             guild_db_name(guild_id)))
        finally:
            await admin.close()

    async def init_guild(self, guild_id: int | str) -> asyncpg.Pool:
        """Create the guild's database and tables if needed; idempotent."""
        name = guild_db_name(guild_id)
        async with self._lock:
            await self._ensure_database(name)
            pool = self._guilds.get(name)
            if pool is None:
                pool = await self._pool(name)
                self._guilds[name] = pool
        async with pool.acquire() as conn:
            await conn.execute(_ddl("guild.sql"))
        return pool

    async def guild(self, guild_id: int | str) -> asyncpg.Pool:
        """Pool for an existing guild database."""
        name = guild_db_name(guild_id)
        pool = self._guilds.get(name)
        if pool is not None:
            return pool
        async with self._lock:
            pool = self._guilds.get(name)
            if pool is None:
                pool = await self._pool(name)
                self._guilds[name] = pool
        return pool

    async def drop_guild(self, guild_id: int | str) -> None:
        name = guild_db_name(guild_id)
        pool = self._guilds.pop(name, None)
        if pool:
            await pool.close()
        admin = await self._connect_admin()
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
            log.info("Dropped database %s", name)
        finally:
            await admin.close()
