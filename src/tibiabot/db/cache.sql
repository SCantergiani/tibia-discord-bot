-- Shared `bot_cache` database. Same tables and columns as the Scala bot's
-- SchemaInitializer.initCache and the cache-side repositories, limited to what
-- the ported features use.

CREATE TABLE IF NOT EXISTS deaths (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  world VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  time VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS levels (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  world VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  level VARCHAR(255) NOT NULL,
  vocation VARCHAR(255) NOT NULL,
  last_login VARCHAR(255) NOT NULL,
  time VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS list (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  world VARCHAR(255) NOT NULL,
  former_worlds VARCHAR(255),
  name VARCHAR(255) NOT NULL,
  former_names VARCHAR(1000),
  level VARCHAR(255) NOT NULL,
  guild_name VARCHAR(255),
  vocation VARCHAR(255) NOT NULL,
  last_login VARCHAR(255) NOT NULL,
  time VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS character_sheet (
  world VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  guild_name VARCHAR(255) NOT NULL,
  vocation VARCHAR(64) NOT NULL,
  char_level INT NOT NULL,
  seen TIMESTAMP NOT NULL,
  PRIMARY KEY (world, name)
);
CREATE INDEX IF NOT EXISTS character_sheet_seen ON character_sheet (seen);

CREATE TABLE IF NOT EXISTS rename_cooldowns (
  channel_id VARCHAR(255) PRIMARY KEY,
  world VARCHAR(255) NOT NULL,
  last_rename TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_statistics_boss (
  world VARCHAR(255) NOT NULL,
  save_day DATE NOT NULL,
  race VARCHAR(255) NOT NULL,
  killed INT NOT NULL,
  players_killed INT NOT NULL,
  PRIMARY KEY (world, save_day, race)
);
CREATE INDEX IF NOT EXISTS kill_statistics_boss_save_day ON kill_statistics_boss (save_day);

CREATE TABLE IF NOT EXISTS kill_statistics_summary (
  world VARCHAR(255) NOT NULL,
  save_day DATE NOT NULL,
  most_killed_race VARCHAR(255) NOT NULL DEFAULT '',
  most_killed INT NOT NULL DEFAULT 0,
  deadliest_race VARCHAR(255) NOT NULL DEFAULT '',
  deadliest_kills INT NOT NULL DEFAULT 0,
  player_deaths INT NOT NULL DEFAULT 0,
  total_killed BIGINT NOT NULL DEFAULT 0,
  total_players_killed INT NOT NULL DEFAULT 0,
  PRIMARY KEY (world, save_day)
);
CREATE INDEX IF NOT EXISTS kill_statistics_summary_save_day ON kill_statistics_summary (save_day);
