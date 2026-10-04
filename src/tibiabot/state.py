"""In-memory view of which guild tracks which world, kept in step with Postgres."""

from __future__ import annotations

from dataclasses import dataclass, field

from tibiabot.db.repos import DiscordInfo, WorldConfig


@dataclass
class GuildState:
    info: DiscordInfo | None = None
    worlds: dict[str, WorldConfig] = field(default_factory=dict)


class BotState:
    def __init__(self) -> None:
        self.guilds: dict[int, GuildState] = {}

    def guild(self, guild_id: int) -> GuildState:
        return self.guilds.setdefault(guild_id, GuildState())

    def set_world(self, guild_id: int, world: WorldConfig) -> None:
        self.guild(guild_id).worlds[world.name] = world

    def remove_world(self, guild_id: int, world: str) -> None:
        self.guild(guild_id).worlds.pop(world, None)

    def forget_guild(self, guild_id: int) -> None:
        self.guilds.pop(guild_id, None)

    def tracked_worlds(self) -> set[str]:
        return {name for g in self.guilds.values() for name in g.worlds}

    def guilds_tracking(self, world: str) -> list[tuple[int, WorldConfig]]:
        return [(gid, g.worlds[world]) for gid, g in self.guilds.items() if world in g.worlds]
