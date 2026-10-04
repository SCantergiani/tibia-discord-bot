"""Who can see the bot's channels: everyone, or only the server's member role
(chosen in /settings -> Member Role).

With a member role, @everyone loses View Channel on every category and channel the
bot made and the role gains it; the command log stays admin-only. Without one,
the @everyone view deny is lifted again. The bot's own overwrites and the
"nobody but the bot posts here" denies are never touched.
"""

from __future__ import annotations

import logging

import discord

from tibiabot.commands_guide import COMMANDS_CHANNEL, same_channel_name
from tibiabot.db.repos import DiscordInfo, WorldConfig
from tibiabot.status import STATUS_CHANNEL

log = logging.getLogger(__name__)

WORLD_CHANNEL_COLUMNS = ("allies_channel", "enemies_channel", "deaths_channel", "levels_channel", "statistics_channel")


def _by_id(guild: discord.Guild, channel_id: str | None) -> discord.abc.GuildChannel | None:
    return guild.get_channel(int(channel_id)) if channel_id and channel_id.isdigit() and channel_id != "0" else None


def member_channels(guild: discord.Guild, info: DiscordInfo | None,
                    worlds: list[WorldConfig]) -> list[discord.abc.GuildChannel]:
    """Everything members should see: the bot's category, notifications and commands
    channels, and every world's category and channels. Not the command log."""
    found: list[discord.abc.GuildChannel | None] = []
    if info:
        category = _by_id(guild, info.admin_category)
        found += [category, _by_id(guild, info.boosted_channel)]
        found += [c for c in getattr(category, "text_channels", [])
                  if any(same_channel_name(c.name, n) for n in (COMMANDS_CHANNEL, STATUS_CHANNEL))]
    for world in worlds:
        found.append(_by_id(guild, world.category))
        found += [_by_id(guild, getattr(world, column)) for column in WORLD_CHANNEL_COLUMNS]
    return [c for c in found if c is not None]


async def apply(guild: discord.Guild, info: DiscordInfo | None, worlds: list[WorldConfig],
                role: discord.Role | None, previous: discord.Role | None = None) -> list[str]:
    """Make the bot's channels visible to `role` only (or to everyone when None).
    Returns the names of channels Discord refused to change."""
    failed = []
    for channel in member_channels(guild, info, worlds):
        try:
            everyone = channel.overwrites_for(guild.default_role)
            everyone.view_channel = False if role else None
            await channel.set_permissions(guild.default_role, overwrite=everyone, reason="member role")
            if previous is not None and previous != role and previous in channel.overwrites:
                await channel.set_permissions(previous, overwrite=None, reason="member role changed")
            if role is not None:
                await channel.set_permissions(role, view_channel=True, read_message_history=True,
                                              reason="member role")
        except discord.HTTPException as e:
            log.warning("Could not set member visibility on %s in %s: %s", channel.name, guild.id, e)
            failed.append(channel.name)
    return failed
