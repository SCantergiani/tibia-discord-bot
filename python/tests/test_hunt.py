import asyncio
from types import SimpleNamespace

import pytest

from tibiabot.cogs import hunt
from tibiabot.cogs.hunt import HuntCog, channel_name


class FakeVoice:
    def __init__(self, channel_id, guild):
        self.id = channel_id
        self.guild = guild
        self.members = []
        self.deleted = False

    async def delete(self, reason=None):
        self.deleted = True


def setup_channel():
    guild = SimpleNamespace(voice_channels=[])
    channel = FakeVoice(42, guild)
    guild.get_channel = lambda cid: channel if cid == 42 and not channel.deleted else None
    return guild, channel


@pytest.fixture(autouse=True)
def fast_grace(monkeypatch):
    monkeypatch.setattr(hunt, "EMPTY_GRACE", 0.05)
    monkeypatch.setattr(hunt.discord, "VoiceChannel", FakeVoice)


def state(channel):
    return SimpleNamespace(channel=channel)


def test_channel_name():
    assert channel_name("  Asura   palace ") == "🏹・Hunt – Asura palace"
    assert channel_name("") == "🏹・Hunt"


async def test_an_emptied_hunt_is_deleted_after_the_grace_period():
    _, channel = setup_channel()
    cog = HuntCog(SimpleNamespace())
    cog.track(channel)
    await cog.on_voice_state_update(None, state(channel), state(None))
    await asyncio.sleep(0.1)
    assert channel.deleted and 42 not in cog.hunts


async def test_someone_rejoining_in_time_keeps_it():
    _, channel = setup_channel()
    cog = HuntCog(SimpleNamespace())
    cog.track(channel)
    await cog.on_voice_state_update(None, state(channel), state(None))
    channel.members = ["back"]
    await cog.on_voice_state_update(None, state(None), state(channel))
    await asyncio.sleep(0.1)
    assert not channel.deleted


async def test_leaving_a_hunt_that_still_has_people_keeps_it():
    _, channel = setup_channel()
    channel.members = ["still here"]
    cog = HuntCog(SimpleNamespace())
    cog.track(channel)
    await cog.on_voice_state_update(None, state(channel), state(None))
    await asyncio.sleep(0.1)
    assert not channel.deleted


async def test_end_hunt_deletes_at_once():
    _, channel = setup_channel()
    channel.members = ["busy"]
    cog = HuntCog(SimpleNamespace())
    cog.track(channel)
    await cog.delete(channel, "ended")
    assert channel.deleted and 42 not in cog.hunts


async def test_other_voice_channels_are_ignored():
    _, channel = setup_channel()
    cog = HuntCog(SimpleNamespace())
    await cog.on_voice_state_update(None, state(channel), state(None))
    await asyncio.sleep(0.1)
    assert not channel.deleted


def test_viewer_role_can_see_but_not_join_and_party_can_join():
    from tibiabot.cogs.hunt import party_overwrites
    class Thing:  # hashable stand-in for a role or member
        pass
    everyone, me, viewers, friend = Thing(), Thing(), Thing(), Thing()
    guild = SimpleNamespace(default_role=everyone, me=me)
    ow = party_overwrites(guild, [friend], viewers)
    assert ow[everyone].view_channel is False and ow[everyone].connect is False
    assert ow[viewers].view_channel is True and ow[viewers].connect is False
    assert ow[friend].view_channel is True and ow[friend].connect is True
    assert viewers not in party_overwrites(guild, [friend])
