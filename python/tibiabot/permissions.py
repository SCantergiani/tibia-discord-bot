"""Who may use what. Checked on every command, button press and form submit:
component ids are client-supplied, so a press is never proof of permission."""

from __future__ import annotations

import discord


def has_manage_server(member: discord.Member | None) -> bool:
    return isinstance(member, discord.Member) and member.guild_permissions.manage_guild


def is_moderator(member: discord.Member | None, moderator_role_id: str | None) -> bool:
    """Manage Server, or the server's moderator role. An unset role id ("0" or
    empty) matches nobody."""
    if has_manage_server(member):
        return True
    if not isinstance(member, discord.Member) or not moderator_role_id or not moderator_role_id.isdigit() \
            or moderator_role_id == "0":
        return False
    return any(role.id == int(moderator_role_id) for role in member.roles)
