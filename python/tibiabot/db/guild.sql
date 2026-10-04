-- One `_<guildId>` database per Discord server. Same tables and columns as the
-- Scala bot's SchemaInitializer.initGuild plus every column its repositories add
-- lazily, consolidated, limited to what the ported features use.

CREATE TABLE IF NOT EXISTS discord_info (
  guild_name VARCHAR(255) NOT NULL,
  guild_owner VARCHAR(255) NOT NULL,
  admin_category VARCHAR(255) NOT NULL,
  admin_channel VARCHAR(255) NOT NULL,
  boosted_channel VARCHAR(255) NOT NULL,
  boosted_messageid VARCHAR(255) NOT NULL,
  flags VARCHAR(255) NOT NULL,
  created TIMESTAMP NOT NULL,
  last_world VARCHAR(255) DEFAULT '0',
  moderator_role VARCHAR(255) DEFAULT '0',
  PRIMARY KEY (guild_name)
);

CREATE TABLE IF NOT EXISTS hunted_players (
  name VARCHAR(255) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  reason_text VARCHAR(255) NOT NULL,
  added_by VARCHAR(255) NOT NULL,
  traded_when_added VARCHAR(255) NOT NULL DEFAULT 'false',
  flagged_reason VARCHAR(255) NOT NULL DEFAULT '',
  flagged_at VARCHAR(255) NOT NULL DEFAULT '',
  tag VARCHAR(255) NOT NULL DEFAULT '',
  PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS hunted_guilds (
  name VARCHAR(255) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  reason_text VARCHAR(255) NOT NULL,
  added_by VARCHAR(255) NOT NULL,
  PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS allied_players (
  name VARCHAR(255) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  reason_text VARCHAR(255) NOT NULL,
  added_by VARCHAR(255) NOT NULL,
  traded_when_added VARCHAR(255) NOT NULL DEFAULT 'false',
  flagged_reason VARCHAR(255) NOT NULL DEFAULT '',
  flagged_at VARCHAR(255) NOT NULL DEFAULT '',
  tag VARCHAR(255) NOT NULL DEFAULT '',
  PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS allied_guilds (
  name VARCHAR(255) NOT NULL,
  reason VARCHAR(255) NOT NULL,
  reason_text VARCHAR(255) NOT NULL,
  added_by VARCHAR(255) NOT NULL,
  PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS worlds (
  name VARCHAR(255) NOT NULL,
  allies_channel VARCHAR(255) NOT NULL,
  enemies_channel VARCHAR(255) NOT NULL,
  neutrals_channel VARCHAR(255) NOT NULL,
  levels_channel VARCHAR(255) NOT NULL,
  deaths_channel VARCHAR(255) NOT NULL,
  category VARCHAR(255) NOT NULL,
  fullbless_role VARCHAR(255) NOT NULL,
  nemesis_role VARCHAR(255) NOT NULL,
  allypk_role VARCHAR(255) NOT NULL,
  masslog_role VARCHAR(255) NOT NULL,
  bounty_role VARCHAR(255) NOT NULL DEFAULT '0',
  fullbless_channel VARCHAR(255) NOT NULL,
  nemesis_channel VARCHAR(255) NOT NULL,
  fullbless_level INT NOT NULL,
  show_neutral_levels VARCHAR(255) NOT NULL,
  show_neutral_deaths VARCHAR(255) NOT NULL,
  show_allies_levels VARCHAR(255) NOT NULL,
  show_allies_deaths VARCHAR(255) NOT NULL,
  show_enemies_levels VARCHAR(255) NOT NULL,
  show_enemies_deaths VARCHAR(255) NOT NULL,
  detect_hunteds VARCHAR(255) NOT NULL,
  levels_min INT NOT NULL,
  deaths_min INT NOT NULL,
  exiva_list VARCHAR(255) NOT NULL,
  online_combined VARCHAR(255) NOT NULL,
  online_allies_min INT NOT NULL DEFAULT 0,
  online_enemies_min INT NOT NULL DEFAULT 0,
  online_neutrals_min INT NOT NULL DEFAULT 0,
  statistics_channel VARCHAR(255) NOT NULL DEFAULT '0',
  statistics_posted VARCHAR(255) NOT NULL DEFAULT '',
  activity_channel VARCHAR(255) DEFAULT '0',
  PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS online_list_categories (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  label VARCHAR(255) NOT NULL,
  emoji VARCHAR(255) NOT NULL,
  added VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS tracked_activity (
  name VARCHAR(255) NOT NULL,
  former_names VARCHAR(255) NOT NULL,
  guild_name VARCHAR(255) NOT NULL,
  updated TIMESTAMP NOT NULL,
  PRIMARY KEY (name)
);

CREATE TABLE IF NOT EXISTS death_screenshots (
  guild_id VARCHAR(100) NOT NULL,
  world VARCHAR(50) NOT NULL,
  character_name VARCHAR(255) NOT NULL,
  death_time BIGINT NOT NULL,
  screenshot_url TEXT NOT NULL,
  added_by VARCHAR(100) NOT NULL,
  added_name VARCHAR(100) NOT NULL,
  added_at TIMESTAMP NOT NULL,
  message_id VARCHAR(100) NOT NULL,
  PRIMARY KEY (guild_id, world, character_name, death_time, screenshot_url)
);

CREATE TABLE IF NOT EXISTS frag_event (
  world VARCHAR(255) NOT NULL,
  save_day DATE NOT NULL,
  killer VARCHAR(255) NOT NULL,
  victim VARCHAR(255) NOT NULL,
  victim_level INT NOT NULL DEFAULT 0,
  victim_side VARCHAR(16) NOT NULL,
  occurred_at TIMESTAMP NOT NULL,
  death_message_id VARCHAR(64) NOT NULL DEFAULT '',
  PRIMARY KEY (world, killer, victim, occurred_at)
);
CREATE INDEX IF NOT EXISTS frag_event_world_day ON frag_event (world, save_day);

-- Respawn board (web only for now; forum_channel/board_thread/thread_id stay at
-- their defaults until the Discord side is ported).
CREATE TABLE IF NOT EXISTS respawn_settings (
  id INT PRIMARY KEY,
  forum_channel VARCHAR(255) NOT NULL DEFAULT '0',
  board_thread VARCHAR(255) NOT NULL DEFAULT '0',
  default_duration INT NOT NULL DEFAULT 120,
  max_duration INT NOT NULL DEFAULT 240,
  queue_limit INT NOT NULL DEFAULT 20,
  stamina_minutes INT NOT NULL DEFAULT 240,
  warn_minutes INT NOT NULL DEFAULT 10,
  handover_minutes INT NOT NULL DEFAULT 10,
  auto_claim BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS respawn_board_state (
  id INT PRIMARY KEY,
  digest VARCHAR(64) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS respawns (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code VARCHAR(32) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  creature VARCHAR(255) NOT NULL DEFAULT '',
  region VARCHAR(255) NOT NULL DEFAULT '',
  world VARCHAR(255) NOT NULL DEFAULT '',
  mapper_link VARCHAR(512) NOT NULL DEFAULT '',
  thread_id VARCHAR(255) NOT NULL DEFAULT '',
  source VARCHAR(16) NOT NULL DEFAULT 'custom',
  added_by VARCHAR(255) NOT NULL DEFAULT '',
  creature_pinned BOOLEAN NOT NULL DEFAULT FALSE,
  max_duration INT
);

CREATE TABLE IF NOT EXISTS respawn_claims (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  respawn_id BIGINT NOT NULL,
  user_id VARCHAR(255) NOT NULL,
  user_name VARCHAR(255) NOT NULL DEFAULT '',
  character_name VARCHAR(255) NOT NULL DEFAULT '',
  status VARCHAR(16) NOT NULL,
  queue_position INT NOT NULL DEFAULT 0,
  claimed_at TIMESTAMPTZ NOT NULL,
  starts_at TIMESTAMPTZ,
  ends_at TIMESTAMPTZ,
  duration_minutes INT NOT NULL,
  warned BOOLEAN NOT NULL DEFAULT FALSE,
  kind VARCHAR(16) NOT NULL DEFAULT 'adhoc',
  limbo_until TIMESTAMPTZ,
  offer_expires_at TIMESTAMPTZ,
  outcome VARCHAR(24),
  ended_at TIMESTAMPTZ,
  schedule_id BIGINT,
  asked_at TIMESTAMPTZ,
  request_deadline TIMESTAMPTZ,
  requester_user_id VARCHAR(255),
  requester_user_name VARCHAR(255),
  requester_nickname VARCHAR(255),
  nickname VARCHAR(255) NOT NULL DEFAULT '',
  requested_starts_at TIMESTAMPTZ,
  requested_duration_minutes INT,
  confirmed_at TIMESTAMPTZ,
  confirm_by TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS respawn_claims_history ON respawn_claims (respawn_id, ended_at DESC);
CREATE INDEX IF NOT EXISTS respawn_claims_guild_history ON respawn_claims (status, ended_at DESC);
CREATE INDEX IF NOT EXISTS respawn_claims_by_respawn ON respawn_claims (respawn_id, status);
CREATE INDEX IF NOT EXISTS respawn_claims_by_deadline ON respawn_claims (status, ends_at);
CREATE INDEX IF NOT EXISTS respawn_claims_by_user ON respawn_claims (user_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS respawn_claims_one_holder ON respawn_claims (respawn_id) WHERE status = 'active';
CREATE UNIQUE INDEX IF NOT EXISTS respawn_claims_occurrence ON respawn_claims (schedule_id, starts_at) WHERE schedule_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS respawn_schedules (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  respawn_id BIGINT NOT NULL,
  user_id VARCHAR(255) NOT NULL,
  user_name VARCHAR(255) NOT NULL DEFAULT '',
  character_name VARCHAR(255) NOT NULL DEFAULT '',
  anchor_at TIMESTAMPTZ NOT NULL,
  period_minutes INT NOT NULL DEFAULT 1440,
  duration_minutes INT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL,
  days_of_week SMALLINT NOT NULL DEFAULT 127,
  nickname VARCHAR(255) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS respawn_schedules_by_respawn ON respawn_schedules (respawn_id, active);

CREATE TABLE IF NOT EXISTS respawn_user_prefs (
  user_id VARCHAR(255) PRIMARY KEY,
  default_duration INT,
  warn_minutes INT
);

CREATE TABLE IF NOT EXISTS respawn_stamina (
  user_id VARCHAR(255) PRIMARY KEY,
  used_minutes INT NOT NULL DEFAULT 0,
  reset_at TIMESTAMPTZ NOT NULL
);
