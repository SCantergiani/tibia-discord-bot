import pytest

from tibiabot.lists.load import estimate
from tibiabot.lists.models import GuildLists, ListedGuild, ListedPlayer


def test_few_online_are_each_checked_at_the_fast_interval():
    load = estimate(tracked=300, online=3, interval=5, cap=2)
    assert load.check_every == 5 and load.gb_per_month == pytest.approx(0.6 * 3.6)


def test_past_the_cap_they_take_turns():
    load = estimate(tracked=300, online=40, interval=5, cap=2)
    assert load.check_every == 20 and load.gb_per_month == pytest.approx(2 * 3.6)


def test_nobody_online_costs_nothing():
    assert estimate(tracked=300, online=0, interval=5, cap=2).gb_per_month == 0


def test_without_a_fast_lane_there_is_no_estimate():
    load = estimate(tracked=10, online=4, interval=None, cap=None)
    assert load.check_every is None and load.text() == "Tracking 10 characters · 4 online now"


def test_tracked_counts_listed_players_and_listed_guild_members_once():
    lists = GuildLists()
    lists.hunted_players["bubble"] = ListedPlayer("bubble")
    lists.allied_players["friend"] = ListedPlayer("friend")
    lists.hunted_guilds["nexus"] = ListedGuild("nexus")
    lists.rosters["nexus"] = {"bubble", "a", "b"}
    lists.rosters["not listed"] = {"x"}
    assert lists.tracked() == {"bubble", "friend", "a", "b"}
