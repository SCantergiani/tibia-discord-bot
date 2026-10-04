"""Against a real Postgres; skipped unless POSTGRES_HOST/POSTGRES_PASSWORD are set
(`docker compose -f docker-compose.dev.yml up -d` provides one)."""

import os

import pytest

from tibiabot.config import Settings
from tibiabot.db import repos
from tibiabot.db.database import Database, guild_db_name
from tibiabot.db.repos import WorldConfig

pytestmark = pytest.mark.skipif(not (os.getenv("POSTGRES_HOST") and os.getenv("POSTGRES_PASSWORD")),
                                reason="needs a Postgres (POSTGRES_HOST, POSTGRES_PASSWORD)")

TEST_GUILD = 999000111222333


@pytest.fixture
async def db():
    settings = Settings(token="x", postgres_host=os.environ["POSTGRES_HOST"],
                        postgres_password=os.environ["POSTGRES_PASSWORD"],
                        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")))
    database = Database(settings)
    await database.start()
    yield database
    await database.drop_guild(TEST_GUILD)
    await database.close()


def test_guild_database_names_must_be_snowflakes():
    assert guild_db_name(123) == "_123"
    with pytest.raises(ValueError):
        guild_db_name("1; DROP DATABASE postgres")


async def test_cache_schema_is_created(db):
    tables = {r["tablename"] for r in await db.cache.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert {"deaths", "levels", "character_sheet", "rename_cooldowns", "kill_statistics_boss"} <= tables


async def test_guild_schema_round_trips_a_world(db):
    pool = await db.init_guild(TEST_GUILD)
    world = WorldConfig(name="Antica", allies_channel="1", enemies_channel="0", neutrals_channel="0",
                        levels_channel="2", deaths_channel="3", category="4", fullbless_role="5",
                        nemesis_role="6", allypk_role="7", statistics_channel="8")
    await repos.save_world(pool, world)
    assert await repos.get_world(pool, "Antica") == world
    await repos.update_world_column(pool, "Antica", "deaths_channel", "33")
    assert (await repos.get_world(pool, "Antica")).deaths_channel == "33"


async def test_init_guild_is_idempotent(db):
    await db.init_guild(TEST_GUILD)
    await db.init_guild(TEST_GUILD)
    assert await db.guild_exists(TEST_GUILD)


async def test_discord_info_keeps_one_row_across_a_rename(db):
    pool = await db.init_guild(TEST_GUILD)
    await repos.save_discord_info(pool, repos.new_discord_info("Old", "owner", "1", "2", "3"))
    await repos.save_discord_info(pool, repos.new_discord_info("New", "owner", "1", "2", "3"))
    assert await pool.fetchval("SELECT count(*) FROM discord_info") == 1
    assert (await repos.get_discord_info(pool)).guild_name == "New"


async def test_only_known_columns_can_be_repaired(db):
    pool = await db.init_guild(TEST_GUILD)
    with pytest.raises(ValueError):
        await repos.update_world_column(pool, "Antica", "name = 'x'; --", "1")
