"""Settings, read once from the environment (and a `.env` file beside it).

Same variable names as the Scala bot, so one `.env` serves either.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PUBLIC_TIBIADATA = "https://api.tibiadata.com"


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    return default if not raw else raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    token: str
    postgres_host: str
    postgres_password: str
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    tibiadata_host: str = PUBLIC_TIBIADATA
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    bot_owner_id: str = ""
    # Guild to register slash commands in instantly while developing; empty
    # registers them globally (Discord takes up to an hour to show those).
    dev_guild_id: str = ""
    character_cache_ttl: int = 300
    character_cache_max_stale: int = 900
    tibiadata_max_in_flight: int = 32
    poll_interval: int = 60
    fast_poll_seconds: float = 5
    fast_poll_max_per_second: float = 2  # starting rate; it adapts to how tibia.com answers
    fast_poll_ceiling: float = 4         # never above this
    ally_poll_seconds: float = 10        # allies are re-checked this often (enemies every fast_poll_seconds)
    masslog_minutes: float = 5    # a mass log: masslog_min_enemies enemies logging in within this
    masslog_min_enemies: int = 5
    tracked_warn_at: int = 200  # warn when adds take a server past this many tracked characters
    emoji_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "data" / "emojis")

    @property
    def fresh_tibiadata(self) -> bool:
        """True for a self-hosted TibiaData, which scrapes tibia.com on every request."""
        return self.tibiadata_host != PUBLIC_TIBIADATA

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_host)


def load(env_file: str | os.PathLike | None = None) -> Settings:
    load_dotenv(env_file)
    missing = [name for name in ("TOKEN", "POSTGRES_HOST", "POSTGRES_PASSWORD") if not os.getenv(name)]
    if missing:
        raise SystemExit(f"Missing required settings: {', '.join(missing)} (see .env.example)")
    emoji_dir = os.getenv("EMOJI_DIR", "").strip()
    return Settings(
        token=os.environ["TOKEN"],
        postgres_host=os.environ["POSTGRES_HOST"],
        postgres_password=os.environ["POSTGRES_PASSWORD"],
        postgres_port=_int("POSTGRES_PORT", 5432),
        postgres_user=os.getenv("POSTGRES_USER", "postgres"),
        tibiadata_host=(os.getenv("TIBIADATA_HOST") or PUBLIC_TIBIADATA).rstrip("/"),
        redis_host=os.getenv("REDIS_HOST", ""),
        redis_port=_int("REDIS_PORT", 6379),
        redis_password=os.getenv("REDIS_PASSWORD", ""),
        bot_owner_id=os.getenv("BOT_OWNER_ID", "").strip(),
        dev_guild_id=os.getenv("DEV_GUILD_ID", "").strip(),
        character_cache_ttl=_int("CHARACTER_CACHE_TTL_SECONDS", 300),
        character_cache_max_stale=_int("CHARACTER_CACHE_MAX_STALE_SECONDS", 900),
        tibiadata_max_in_flight=_int("TIBIADATA_MAX_IN_FLIGHT", 32),
        # With a self-hosted TibiaData the watcher starts a full poll the moment tibia.com
        # refreshes the online list (once a minute), so the timed poll is only a safety net.
        poll_interval=_int("POLL_INTERVAL_SECONDS", 60),
        fast_poll_seconds=float(os.getenv("FAST_POLL_SECONDS", "") or 5),
        fast_poll_max_per_second=float(os.getenv("FAST_POLL_MAX_PER_SECOND", "") or 2),
        fast_poll_ceiling=float(os.getenv("FAST_POLL_CEILING", "") or 4),
        ally_poll_seconds=float(os.getenv("ALLY_POLL_SECONDS", "") or 10),
        masslog_minutes=float(os.getenv("MASSLOG_MINUTES", "") or 5),
        masslog_min_enemies=_int("MASSLOG_MIN_ENEMIES", 5),
        tracked_warn_at=_int("TRACKED_WARN_AT", 200),
        **({"emoji_dir": Path(emoji_dir)} if emoji_dir else {}),
    )
