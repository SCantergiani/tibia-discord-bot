import pytest

from tibiabot.lists.load import estimate
from tibiabot.lists.models import GuildLists, ListedGuild, ListedPlayer


def test_few_online_are_checked_on_their_schedules():
    load = estimate(300, enemies=3, allies=4, enemy_every=5, ally_every=10, cap=2)
    assert (load.enemy_every, load.ally_every) == (5, 10)
    assert load.gb_per_month == pytest.approx((3 / 5 + 4 / 10) * 3.6)


def test_allies_get_what_the_enemies_leave():
    load = estimate(300, enemies=5, allies=10, enemy_every=5, ally_every=10, cap=2)
    assert load.enemy_every == 5 and load.ally_every == 10      # 1/s + 1/s fits exactly
    load = estimate(300, enemies=5, allies=20, enemy_every=5, ally_every=10, cap=2)
    assert load.enemy_every == 5 and load.ally_every == 20      # allies share the 1/s left
    assert load.gb_per_month == pytest.approx(2 * 3.6)


def test_enough_enemies_use_the_whole_rate():
    load = estimate(300, enemies=40, allies=5, enemy_every=5, ally_every=10, cap=2)
    assert load.enemy_every == 20 and load.ally_every is None
    assert "allies wait for the enemies" in load.text()


def test_nobody_online_costs_nothing():
    assert estimate(300, 0, 0, 5, 10, 2).gb_per_month == 0


def test_without_a_fast_lane_there_is_no_estimate():
    load = estimate(10, 4, 1, None, None, None)
    assert load.enemy_every is None and load.text() == "Tracking 10 characters · 4 enemies and 1 allies online"


def test_sides_and_tracked_count_listed_players_and_listed_guild_members_once():
    lists = GuildLists()
    lists.hunted_players["bubble"] = ListedPlayer("bubble")
    lists.allied_players["friend"] = ListedPlayer("friend")
    lists.hunted_guilds["nexus"] = ListedGuild("nexus")
    lists.rosters["nexus"] = {"bubble", "a", "b"}
    lists.rosters["not listed"] = {"x"}
    assert lists.side_names(True) == {"bubble", "a", "b"} and lists.side_names(False) == {"friend"}
    assert lists.tracked() == {"bubble", "friend", "a", "b"}
