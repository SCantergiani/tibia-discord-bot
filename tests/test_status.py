from types import SimpleNamespace

import pytest

from tibiabot.config import Settings
from tibiabot.db.repos import WorldConfig
from tibiabot.lists.models import GuildLists, ListedGuild, ListedPlayer
from tibiabot.online import WorldOnline
from tibiabot.ratelimit import AdaptiveRate
from tibiabot.state import BotState
from tibiabot.stats import Stats
from tibiabot.status import status_embed
from tibiabot.tibiadata.models import OnlinePlayer


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_check_intervals_and_death_delays_are_averaged_over_their_windows():
    clock = Clock()
    stats = Stats(clock)
    stats.record_check("enemy", 5)
    stats.record_check("enemy", 7)
    stats.record_check("ally", 10)
    assert stats.check_every("enemy") == 6 and stats.check_every("ally") == 10
    clock.t += 601
    assert stats.check_every("enemy") is None  # older than 10 minutes
    stats.record_death("enemy", 8)
    stats.record_death("enemy", 12)
    assert stats.death_delay("enemy") == (10, 2) and stats.death_delay("ally") is None
    clock.t += 24 * 3600 + 1
    assert stats.death_delay("enemy") is None


def test_status_message_shows_what_was_measured():
    state = BotState()
    state.set_world(1, WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7"))
    lists = GuildLists()
    lists.hunted_guilds["nexus"] = ListedGuild("nexus")
    lists.rosters["nexus"] = {"supremo alvesz"}
    lists.allied_players["friend"] = ListedPlayer("friend")
    world_online = WorldOnline()
    world_online.update([OnlinePlayer("Supremo Alvesz", 460, "Knight"), OnlinePlayer("Friend", 200, "Druid"),
                         OnlinePlayer("Random", 100, "Sorcerer")], first_poll=False)
    stats = Stats()
    stats.record_check("enemy", 5.1)
    stats.record_check("ally", 10.2)
    stats.record_death("enemy", 8)
    poller = SimpleNamespace(phase=39.0, last_poll=1_800_000_000)
    bot = SimpleNamespace(state=state, lists=SimpleNamespace(of=lambda _: lists), online={"Inabra": world_online},
                          pollers=SimpleNamespace(get=lambda _: poller), stats=stats,
                          rate=AdaptiveRate(2, 4), settings=Settings(token="x", postgres_host="x",
                                                                     postgres_password="x"))
    embed = status_embed(bot, 1)
    assert "**Inabra**: 💀 **1** enemies · 🤍 **1** allies online" in embed.description
    assert "**:39** each minute" in embed.description
    fields = {f.name: f.value for f in embed.fields}
    checks = next(v for k, v in fields.items() if k.startswith("How often"))
    assert "Enemies: every **~5s**" in checks and "Allies: every **~10s**" in checks
    assert "Enemies: **~8s** (1 deaths)" in fields["Deaths posted after they happen (last 24 h)"]
    assert "**2/s** now" in fields["tibia.com request rate"]


async def test_fast_lane_records_how_long_each_character_waited():
    from tibiabot.poller import FastLane, WorldPoller
    from tests.test_poller import FakeClient, FakeSheets, sides, world
    stats = Stats()
    client, sheets = FakeClient(), FakeSheets()
    client.online = world("Enemy A", "Ally B")
    poller = WorldPoller("Antica", client, sheets, [], priority=sides, fast_lane=FastLane(5, 2, ally_interval=10),
                         stats=stats)
    await poller.tick()
    poller.fast_candidates(now=0)
    poller.fast_candidates(now=5)
    poller.fast_candidates(now=10)
    assert stats.check_every("enemy") == pytest.approx(5) and stats.check_every("ally") == pytest.approx(10)
