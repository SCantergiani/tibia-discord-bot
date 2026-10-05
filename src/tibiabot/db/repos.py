"""Reads and writes for the per-guild `discord_info` and `worlds` tables."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone

import asyncpg

NONE_ID = "0"


@dataclass
class DiscordInfo:
    guild_name: str
    guild_owner: str
    admin_category: str
    admin_channel: str
    boosted_channel: str
    boosted_messageid: str
    flags: str
    created: datetime
    last_world: str = NONE_ID
    moderator_role: str = NONE_ID
    member_role: str = NONE_ID  # only this role sees the bot's channels and hunts ('0': everyone / party)


@dataclass
class WorldConfig:
    """One row of `worlds`. Field names are the column names."""
    name: str
    allies_channel: str
    enemies_channel: str
    neutrals_channel: str
    levels_channel: str
    deaths_channel: str
    category: str
    fullbless_role: str
    nemesis_role: str
    allypk_role: str
    masslog_role: str = NONE_ID
    bounty_role: str = NONE_ID
    fullbless_channel: str = NONE_ID
    nemesis_channel: str = NONE_ID
    fullbless_level: int = 250
    show_neutral_levels: str = "true"
    show_neutral_deaths: str = "true"
    show_allies_levels: str = "true"
    show_allies_deaths: str = "true"
    show_enemies_levels: str = "true"
    show_enemies_deaths: str = "true"
    detect_hunteds: str = "on"
    levels_min: int = 8
    deaths_min: int = 8
    exiva_list: str = "false"
    exiva_count: int = 5  # 0 = every killer
    online_combined: str = "true"
    online_allies_min: int = 0
    online_enemies_min: int = 0
    online_neutrals_min: int = 0
    statistics_channel: str = NONE_ID
    statistics_posted: str = ""
    activity_channel: str = NONE_ID


WORLD_COLUMNS = tuple(f.name for f in fields(WorldConfig))
DISCORD_COLUMNS = tuple(f.name for f in fields(DiscordInfo))
# Channel/role columns `/repair` may rewrite; anything else is refused so a
# column name never comes from outside this module.
REPAIRABLE_COLUMNS = frozenset({
    "allies_channel", "enemies_channel", "levels_channel", "deaths_channel", "category", "statistics_channel",
    "fullbless_role", "nemesis_role", "allypk_role", "masslog_role",
})


async def get_discord_info(pool: asyncpg.Pool) -> DiscordInfo | None:
    row = await pool.fetchrow(f"SELECT {', '.join(DISCORD_COLUMNS)} FROM discord_info LIMIT 1")
    return DiscordInfo(**dict(row)) if row else None


async def save_discord_info(pool: asyncpg.Pool, info: DiscordInfo) -> None:
    cols = ", ".join(DISCORD_COLUMNS)
    params = ", ".join(f"${i}" for i in range(1, len(DISCORD_COLUMNS) + 1))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in DISCORD_COLUMNS if c != "guild_name")
    async with pool.acquire() as conn, conn.transaction():
        # One row per guild: the guild's name is the key, and a rename must
        # replace the row rather than add a second.
        await conn.execute("DELETE FROM discord_info WHERE guild_name <> $1", info.guild_name)
        await conn.execute(
            f"INSERT INTO discord_info ({cols}) VALUES ({params}) ON CONFLICT (guild_name) DO UPDATE SET {updates}",
            *(getattr(info, c) for c in DISCORD_COLUMNS))


def new_discord_info(guild_name: str, owner: str, admin_category: str, admin_channel: str,
                     notifications_channel: str) -> DiscordInfo:
    return DiscordInfo(guild_name=guild_name, guild_owner=owner, admin_category=admin_category,
                       admin_channel=admin_channel, boosted_channel=notifications_channel,
                       boosted_messageid=NONE_ID, flags=NONE_ID,
                       created=datetime.now(timezone.utc).replace(tzinfo=None))


async def list_worlds(pool: asyncpg.Pool) -> list[WorldConfig]:
    rows = await pool.fetch(f"SELECT {', '.join(WORLD_COLUMNS)} FROM worlds ORDER BY name")
    return [WorldConfig(**dict(r)) for r in rows]


async def get_world(pool: asyncpg.Pool, world: str) -> WorldConfig | None:
    row = await pool.fetchrow(f"SELECT {', '.join(WORLD_COLUMNS)} FROM worlds WHERE name = $1", world)
    return WorldConfig(**dict(row)) if row else None


async def save_world(pool: asyncpg.Pool, world: WorldConfig) -> None:
    cols = ", ".join(WORLD_COLUMNS)
    params = ", ".join(f"${i}" for i in range(1, len(WORLD_COLUMNS) + 1))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in WORLD_COLUMNS if c != "name")
    await pool.execute(
        f"INSERT INTO worlds ({cols}) VALUES ({params}) ON CONFLICT (name) DO UPDATE SET {updates}",
        *(getattr(world, c) for c in WORLD_COLUMNS))


# Per-world settings the panels may change, and the type each one holds.
SETTING_COLUMNS: dict[str, type] = {
    "show_neutral_levels": str, "show_neutral_deaths": str, "show_allies_levels": str, "show_allies_deaths": str,
    "show_enemies_levels": str, "show_enemies_deaths": str, "detect_hunteds": str, "exiva_list": str,
    "exiva_count": int,
    "online_combined": str, "fullbless_level": int, "levels_min": int, "deaths_min": int,
    "online_allies_min": int, "online_enemies_min": int, "online_neutrals_min": int,
    # A role id (ping that role), "everyone" (ping @everyone) or "0" (no mass-log alert).
    "masslog_role": str,
    "statistics_posted": str,  # ISO date of the last daily statistics post
}


async def update_world_setting(pool: asyncpg.Pool, world: str, column: str, value: str | int) -> None:
    kind = SETTING_COLUMNS.get(column)
    if kind is None or not isinstance(value, kind):
        raise ValueError(f"not a world setting: {column}={value!r}")
    await pool.execute(f"UPDATE worlds SET {column} = $1 WHERE name = $2", value, world)


async def update_world_column(pool: asyncpg.Pool, world: str, column: str, value: str) -> None:
    if column not in REPAIRABLE_COLUMNS:
        raise ValueError(f"not a repairable column: {column}")
    await pool.execute(f"UPDATE worlds SET {column} = $1 WHERE name = $2", value, world)


async def delete_world(pool: asyncpg.Pool, world: str) -> None:
    await pool.execute("DELETE FROM worlds WHERE name = $1", world)


async def set_moderator_role(pool: asyncpg.Pool, role_id: str) -> None:
    await pool.execute("UPDATE discord_info SET moderator_role = $1", role_id)
