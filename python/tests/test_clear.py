from dataclasses import replace
from types import SimpleNamespace

import discord

from tibiabot.cogs import clear as clear_mod
from tibiabot.db.repos import WorldConfig
from tibiabot.state import BotState

WORLD = WorldConfig("Inabra", "1", "0", "0", "200", "100", "4", "5", "6", "7")


class FakeChannel(discord.TextChannel):
    def __init__(self, channel_id, position=3):  # noqa: D401 - stands in for a real channel
        self.id = channel_id
        self.position = position
        self.deleted = False
        self.sent = []
        self.moved_to = None

    async def clone(self, reason=None):
        return FakeChannel(self.id + 1000)

    async def edit(self, position=None):
        self.moved_to = position

    async def delete(self, reason=None):
        self.deleted = True

    async def send(self, embed=None, **kw):
        self.sent.append(embed)


async def test_clearing_replaces_the_channel_and_remembers_the_new_one(monkeypatch):
    deaths = FakeChannel(100)
    guild = SimpleNamespace(id=1, get_channel=lambda cid: deaths if cid == 100 else None)
    state = BotState()
    state.set_world(1, WORLD)
    written = {}

    async def update_world_column(pool, world, column, value):
        written[column] = value

    async def guild_pool(_):
        return None

    monkeypatch.setattr(clear_mod.repos, "update_world_column", update_world_column)
    bot = SimpleNamespace(state=state, db=SimpleNamespace(guild=guild_pool))
    new = await clear_mod.clear_channel(bot, guild, WORLD, "deaths_channel", "test")
    assert deaths.deleted and new.id == 1100 and new.moved_to == 3
    assert written == {"deaths_channel": "1100"} and state.guild(1).worlds["Inabra"].deaths_channel == "1100"
    assert new.sent and "deaths" in new.sent[0].description


async def test_a_missing_channel_is_reported_not_created():
    guild = SimpleNamespace(id=1, get_channel=lambda cid: None)
    bot = SimpleNamespace(state=BotState())
    assert await clear_mod.clear_channel(bot, guild, replace(WORLD, levels_channel="0"), "levels_channel", "t") is None
