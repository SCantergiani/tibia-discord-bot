"""Postgres access for the hunted/allied lists, the shared list cache and the
per-guild activity roster. Table names come only from the constants below."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import asyncpg

from tibiabot.lists.models import GuildLists, ListedGuild, ListedPlayer

PLAYER_TABLES = {True: "hunted_players", False: "allied_players"}
GUILD_TABLES = {True: "hunted_guilds", False: "allied_guilds"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def load_lists(pool: asyncpg.Pool) -> GuildLists:
    lists = GuildLists()
    for hunted in (True, False):
        for row in await pool.fetch(
                f"SELECT name, reason, reason_text, added_by, traded_when_added, flagged_reason, flagged_at, tag "
                f"FROM {PLAYER_TABLES[hunted]}"):
            player = ListedPlayer(row["name"].lower(), row["reason"], row["reason_text"], row["added_by"],
                                  row["traded_when_added"] == "true", row["flagged_reason"] or "",
                                  row["flagged_at"] or "", row["tag"] or "")
            lists.players(hunted)[player.name] = player
        for row in await pool.fetch(f"SELECT name, reason, reason_text, added_by FROM {GUILD_TABLES[hunted]}"):
            lists.guilds(hunted)[row["name"].lower()] = ListedGuild(row["name"].lower(), row["reason"],
                                                                     row["reason_text"], row["added_by"])
    return lists


async def add_player(pool: asyncpg.Pool, hunted: bool, p: ListedPlayer) -> None:
    await pool.execute(
        f"INSERT INTO {PLAYER_TABLES[hunted]} (name, reason, reason_text, added_by, traded_when_added, tag) "
        "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (name) DO NOTHING",
        p.name, p.reason, p.reason_text, p.added_by, "true" if p.traded_when_added else "false", p.tag)


async def add_guild(pool: asyncpg.Pool, hunted: bool, g: ListedGuild) -> None:
    await pool.execute(
        f"INSERT INTO {GUILD_TABLES[hunted]} (name, reason, reason_text, added_by) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (name) DO NOTHING", g.name, g.reason, g.reason_text, g.added_by)


async def remove_player(pool: asyncpg.Pool, hunted: bool, name: str) -> None:
    await pool.execute(f"DELETE FROM {PLAYER_TABLES[hunted]} WHERE LOWER(name) = LOWER($1)", name)


async def remove_guild(pool: asyncpg.Pool, hunted: bool, name: str) -> None:
    await pool.execute(f"DELETE FROM {GUILD_TABLES[hunted]} WHERE LOWER(name) = LOWER($1)", name)


async def clear(pool: asyncpg.Pool, hunted: bool) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(f"DELETE FROM {PLAYER_TABLES[hunted]}")
        await conn.execute(f"DELETE FROM {GUILD_TABLES[hunted]}")


async def set_tag(pool: asyncpg.Pool, name: str, tag: str) -> None:
    await pool.execute("UPDATE hunted_players SET tag = $1 WHERE LOWER(name) = LOWER($2)", tag, name)


async def flag_player(pool: asyncpg.Pool, hunted: bool, name: str, reason: str) -> str:
    """Flag once; returns the timestamp stored. Same ISO form the Scala bot wrote."""
    at = _now().isoformat()
    await pool.execute(
        f"UPDATE {PLAYER_TABLES[hunted]} SET flagged_reason = $1, flagged_at = $2 "
        "WHERE LOWER(name) = LOWER($3) AND flagged_reason = ''", reason, at, name)
    return at


async def unflag_player(pool: asyncpg.Pool, hunted: bool, name: str) -> None:
    await pool.execute(f"UPDATE {PLAYER_TABLES[hunted]} SET flagged_reason = '', flagged_at = '' "
                       "WHERE LOWER(name) = LOWER($1)", name)


# --- activity roster (members of listed guilds, for join/leave detection) ---

async def add_activity(pool: asyncpg.Pool, rows: list[tuple[str, str]]) -> None:
    """(character name, guild name) pairs; existing characters keep their row."""
    if rows:
        now = _now().replace(tzinfo=None)
        await pool.executemany(
            "INSERT INTO tracked_activity (name, former_names, guild_name, updated) VALUES ($1, '', $2, $3) "
            "ON CONFLICT (name) DO NOTHING", [(name, guild, now) for name, guild in rows])


async def remove_activity_by_names(pool: asyncpg.Pool, names: list[str]) -> None:
    if names:
        await pool.execute("DELETE FROM tracked_activity WHERE LOWER(name) = ANY($1::text[])",
                           [n.lower() for n in names])


async def remove_activity_by_guilds(pool: asyncpg.Pool, guilds: list[str]) -> None:
    if guilds:
        await pool.execute("DELETE FROM tracked_activity WHERE LOWER(guild_name) = ANY($1::text[])",
                           [g.lower() for g in guilds])


async def activity_counts(pool: asyncpg.Pool) -> dict[str, int]:
    rows = await pool.fetch("SELECT LOWER(guild_name) AS g, count(*) AS n FROM tracked_activity "
                            "WHERE guild_name <> '' GROUP BY LOWER(guild_name)")
    return {r["g"]: r["n"] for r in rows}


# --- shared list cache (bot_cache.list): last known sheet of listed players ---

@dataclass(frozen=True)
class CachedSheet:
    name: str
    world: str
    level: str
    vocation: str
    guild_name: str
    last_login: str
    updated: datetime | None


async def cache_sheet(cache: asyncpg.Pool, name: str, former_names: list[str], world: str,
                      former_worlds: list[str], guild: str, level: int, vocation: str, last_login: str) -> None:
    now = _now().isoformat()
    async with cache.acquire() as conn, conn.transaction():
        updated = await conn.execute(
            "UPDATE list SET former_names = $1, world = $2, former_worlds = $3, guild_name = $4, level = $5, "
            "vocation = $6, last_login = $7, time = $8, name = $9 WHERE LOWER(name) = LOWER($9)",
            ",".join(former_names), world, ",".join(former_worlds), guild, str(level), vocation, last_login, now, name)
        if updated == "UPDATE 0":
            await conn.execute(
                "INSERT INTO list (name, former_names, world, former_worlds, guild_name, level, vocation, "
                "last_login, time) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                name, ",".join(former_names), world, ",".join(former_worlds), guild, str(level), vocation,
                last_login, now)


async def cached_sheets(cache: asyncpg.Pool, names: list[str]) -> dict[str, CachedSheet]:
    if not names:
        return {}
    rows = await cache.fetch("SELECT name, world, level, vocation, guild_name, last_login, time FROM list "
                             "WHERE LOWER(name) = ANY($1::text[])", [n.lower() for n in names])
    result = {}
    for r in rows:
        try:
            updated = datetime.fromisoformat(r["time"])
        except (TypeError, ValueError):
            updated = None
        result[r["name"].lower()] = CachedSheet(r["name"], r["world"], r["level"], r["vocation"],
                                                r["guild_name"] or "", r["last_login"], updated)
    return result
