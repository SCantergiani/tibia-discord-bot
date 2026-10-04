from datetime import datetime, timezone

import discord

from tibiabot.lists import embeds as e
from tibiabot.lists.models import BulkOutcome, ListedPlayer, find_tag
from tibiabot.lists.repo import CachedSheet

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def sheet(name, world, level, vocation, guild=""):
    return CachedSheet(name, world, str(level), vocation, guild, "2026-01-01T00:00:00Z", NOW)


def test_players_grouped_by_world_then_vocation_then_level():
    listed = [ListedPlayer(n.lower()) for n in ("Knight Low", "Knight High", "Druid", "Far Away", "Unknown")]
    sheets = {
        "knight low": sheet("Knight Low", "Antica", 100, "Elite Knight"),
        "knight high": sheet("Knight High", "Antica", 500, "Knight"),
        "druid": sheet("Druid", "Antica", 50, "Elder Druid"),
        "far away": sheet("Far Away", "Bona", 10, "Sorcerer"),
    }
    lines = e.player_lines(listed, sheets, set(), set(), hunted_list=True, now=NOW)
    names = [l.split("[")[1].split("]")[0] if "[" in l else l for l in lines]
    assert names == ["## Antica", "Druid", "Knight High", "Knight Low", "## Bona", "Far Away",
                     "## Not checked yet", "Unknown"]


def test_tag_and_flag_marks_are_shown():
    listed = [ListedPlayer("bubble", tag="rat", flagged_reason="traded", flagged_at="2026-10-01T00:00:00+00:00")]
    line = e.player_lines(listed, {"bubble": sheet("Bubble", "Antica", 1, "Knight")}, set(), set(), True, NOW)[1]
    assert "🐀" in line and ":triangular_flag_on_post:" in line and "<t:" in line


def test_recent_login_only_within_a_day():
    assert e.recent_login("2026-10-04T06:00:00Z", NOW).endswith(":R>")
    assert e.recent_login("2026-09-01T00:00:00Z", NOW) == ""
    assert e.recent_login("", NOW) == ""


def test_guild_icon_classification():
    # hunted list: player in a hunted guild gets the enemy-guild icon alone
    assert e.guild_icon("Bad Guys", allied_guild=False, hunted_guild=True, hunted_list=True) == \
        e.guild_icon("x", False, True, True)
    assert e.guild_icon("", False, False, True) != e.guild_icon("Neutral", False, False, True)


def test_pack_never_strands_a_heading_at_the_end_of_a_page():
    lines = ["## World A"] + ["x" * 50] * 3 + ["## World B", "y" * 50]
    pages = e.pack(lines, limit=220)
    for page in pages:
        assert not page.splitlines()[-1].startswith("## ")
    assert sum(len(p.splitlines()) for p in pages) == len(lines)


def test_batches_respect_ten_embeds_and_6000_characters():
    small = [discord.Embed(description="x") for _ in range(25)]
    assert [len(b) for b in e.batches(small)] == [10, 10, 5]
    big = [discord.Embed(description="x" * 4000) for _ in range(3)]
    assert [len(b) for b in e.batches(big)] == [1, 1, 1]


def test_bulk_reply_headline_and_groups():
    embed = e.bulk(True, "player", True, BulkOutcome(added=["Bubble", "Charm"], not_found=["Nobody"],
                                                     unavailable=["Laggy"]), find_tag("rat"))
    assert embed.description.startswith("**2** players added to the hunted list.")
    assert "Tagged 🐀 **Rat**" in embed.description
    assert "didn't answer for 1" in embed.description
    assert [f.name.split(" (")[0].split(" ", 1)[-1] for f in embed.fields] == \
        ["Added", "No such character", "Couldn't check"]


def test_bulk_remove_wording():
    embed = e.bulk(False, "guild", False, BulkOutcome(added=["Wrath"], not_found=["Nope"]))
    assert embed.description == "**1** guild removed from the allies list."
    assert any("Not on the list" in f.name for f in embed.fields)
