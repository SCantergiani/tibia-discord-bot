from types import SimpleNamespace

import discord

from tibiabot import visibility
from tibiabot.commands_guide import COMMANDS_CHANNEL
from tibiabot.db.repos import WorldConfig, new_discord_info


class Thing:
    """Hashable stand-in for a role."""

    def __init__(self, name):
        self.name = name


class FakeChannel:
    def __init__(self, cid, name, overwrites=None):
        self.id, self.name = cid, name
        self.overwrites = dict(overwrites or {})
        self.text_channels = []

    def overwrites_for(self, target):
        return self.overwrites.get(target, discord.PermissionOverwrite())

    async def set_permissions(self, target, *, overwrite=..., reason=None, **perms):
        if overwrite is None:
            self.overwrites.pop(target, None)
        elif overwrite is ...:
            self.overwrites[target] = discord.PermissionOverwrite(**perms)
        else:
            self.overwrites[target] = overwrite


def fake_guild():
    everyone = Thing("@everyone")
    category = FakeChannel(1, "Popaco Bot", {everyone: discord.PermissionOverwrite(view_channel=True)})
    log_channel = FakeChannel(2, "🖥️・ᴄᴏᴍᴍᴀɴᴅ-ʟᴏɢ", {everyone: discord.PermissionOverwrite(view_channel=False)})
    notes = FakeChannel(3, "👑・ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴs", {everyone: discord.PermissionOverwrite(send_messages=False)})
    guide = FakeChannel(4, COMMANDS_CHANNEL, {everyone: discord.PermissionOverwrite(send_messages=False)})
    category.text_channels = [log_channel, notes, guide]
    world_cat = FakeChannel(10, "Inabra")
    world_chans = [FakeChannel(i, f"c{i}", {everyone: discord.PermissionOverwrite(send_messages=False)})
                   for i in (11, 12, 13, 14)]
    by_id = {c.id: c for c in [category, log_channel, notes, guide, world_cat, *world_chans]}
    guild = SimpleNamespace(default_role=everyone, get_channel=by_id.get)
    info = new_discord_info("G", "o", "1", "2", "3")
    world = WorldConfig("Inabra", "11", "0", "0", "13", "12", "10", "5", "6", "7", statistics_channel="14")
    return guild, info, world, by_id


async def test_member_role_hides_everything_but_keeps_the_command_log_admin_only():
    guild, info, world, by_id = fake_guild()
    members = Thing("Miembros")
    assert await visibility.apply(guild, info, [world], members) == []
    for cid in (1, 3, 4, 10, 11, 12, 13, 14):
        channel = by_id[cid]
        assert channel.overwrites[guild.default_role].view_channel is False, channel.name
        assert channel.overwrites[members].view_channel is True, channel.name
    assert by_id[3].overwrites[guild.default_role].send_messages is False  # still nobody posts there
    assert members not in by_id[2].overwrites and by_id[2].overwrites[guild.default_role].view_channel is False


async def test_clearing_or_changing_the_role_undoes_the_old_one():
    guild, info, world, by_id = fake_guild()
    old, new = Thing("Old"), Thing("New")
    await visibility.apply(guild, info, [world], old)
    await visibility.apply(guild, info, [world], new, previous=old)
    assert old not in by_id[11].overwrites and by_id[11].overwrites[new].view_channel is True
    await visibility.apply(guild, info, [world], None, previous=new)
    assert new not in by_id[11].overwrites and by_id[11].overwrites[guild.default_role].view_channel is None
