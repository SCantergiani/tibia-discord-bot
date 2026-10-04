"""Ported from OnlineListEmbedsSpec, OnlineListGroupingSpec and MasslogDetectorSpec,
plus the combined-list builder."""

from tibiabot import online
from tibiabot.db.repos import WorldConfig
from tibiabot.lists.models import GuildLists, ListedGuild, ListedPlayer
from tibiabot.tibiadata.models import OnlinePlayer

WORLD = WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7")


# --- small pieces -----------------------------------------------------------

def test_duration_text():
    assert online.duration_text(0, True) == "`0min`"
    assert online.duration_text(59 * 60, True) == "`59min`"
    assert online.duration_text(125 * 60, True) == "`2hr 5min`"
    assert online.duration_text(60, False) == "`1min+`"


def test_base_name():
    assert online.base_name("online-42", "online") == "online"
    assert online.base_name("ɴᴇᴍᴇsɪs-5", "enemies") == "ɴᴇᴍᴇsɪs"
    assert online.base_name("allies", "allies") == "allies"
    assert online.base_name("my-cool-list-99", "online") == "my-cool-list"
    assert online.base_name("online-⚠️", "online") == "online"


def test_category_name():
    assert online.category_name("Antica", 5, 2) == "Antica・🤍5💀2"
    assert online.category_name("Antica", 5, 0) == "Antica・🤍5"
    assert online.category_name("Antica", 0, 3) == "Antica・💀3"
    assert online.category_name("Antica", 0, 0) == "Antica"


def test_masslog_thresholds():
    assert [online.required_zaps(n) for n in (0, 1, 5, 10, 20, 21, 25)] == [3, 3, 4, 7, 10, 9, 10]
    assert online.is_masslog(4, 5) and not online.is_masslog(3, 5)
    assert online.is_masslog(20, 25) and not online.is_masslog(0, 5)


# --- grouping ---------------------------------------------------------------

def test_group_by_guild_biggest_first_guildless_last():
    rows = [("", "a"), ("Small", "b"), ("Big", "c"), ("Big", "d"), ("", "e"), ("", "f")]
    assert online.group_by_guild(rows) == [("Big", ["c", "d"]), ("Small", ["b"]), ("", ["a", "e", "f"])]
    assert online.group_by_guild([]) == []


def test_with_headers():
    lines = online.with_headers([("Big", ["c"]), ("", ["a"])], lambda n: f"### Others {n}")
    assert lines[0].startswith("### [Big](") and lines[0].endswith(" 1")
    assert lines[1:] == ["c", "### Others 1", "a"]


def test_combined_body_headers_only_when_categories_mix():
    assert online.combined_body(["a"], [], [], []) == ["a"]
    body = online.combined_body(["a"], ["e"], ["n"], ["### Others 1", "n"])
    assert "**Allies**" in body[0] and body[1] == "a" and "**Enemies**" in body[2] and body[3] == "e"
    assert body[4:] == ["### Others 1", "n"]
    # only neutrals with no guild headers: the lone "Others" header is dropped
    assert online.combined_body([], [], ["n"], ["### Others 1", "n"]) == ["n"]


# --- packing ----------------------------------------------------------------

def test_pack_small_list_is_one_embed():
    assert online.pack_messages(["a", "b", "c"]) == [["a\nb\nc"]]


def test_section_header_starts_a_new_embed_on_the_same_message():
    assert online.pack_messages(["a", "### Neutrals", "b"]) == [["a", "### Neutrals\nb"]]
    assert online.pack_messages(["### Neutrals", "b"]) == [["### Neutrals\nb"]]


def test_guild_header_stays_with_the_preceding_lines():
    assert online.pack_messages(["a", "### [Guild](u)", "b"]) == [["a\n### [Guild](u)\nb"]]


def test_full_embed_rolls_to_a_second_embed_then_a_second_message():
    assert online.pack_messages(["x" * 2900, "y" * 100]) == [["x" * 2900, "y" * 100]]
    packed = online.pack_messages(["x" * 2900, "y" * 2900, "z" * 100])
    assert len(packed) == 2 and len(packed[0]) == 2 and packed[1] == ["z" * 100]


def test_incoming_guild_header_breaks_the_embed_early():
    assert online.pack_messages(["x" * 2730, "### [G](u)"]) == [["x" * 2730, "### [G](u)"]]


def test_at_most_ten_embeds_per_message():
    assert [len(m) for m in online.pack_messages(["### Section"] * 11)] == [10, 1]


def test_realistic_roster_stays_inside_discord_caps():
    lines = []
    for g in range(15):
        lines.append(f"### [Guild {g}](https://example.test/{g}) 20")
        lines += [f":shield: **{500 + i}** — **[Player Name {g}-{i}](https://www.tibia.com/community/?name=x)** "
                  f"`1hr 2min`" for i in range(20)]
    for message in online.pack_messages(lines):
        assert len(message) <= 10 and sum(len(d) for d in message) <= 6000
        assert all(len(d) <= 4096 for d in message)
        assert not message[-1].splitlines()[-1].startswith("### ")


# --- the list for one server ------------------------------------------------

def test_build_sections_counts_and_zap():
    lists = GuildLists()
    lists.hunted_guilds["nexus"] = ListedGuild("nexus")
    lists.allied_players["friend"] = ListedPlayer("friend")
    wo = online.WorldOnline()
    wo.update([OnlinePlayer("Old Enemy", 400, "Elite Knight")], first_poll=True, now=1000)
    wo.update([OnlinePlayer("Old Enemy", 400, "Elite Knight"), OnlinePlayer("New Enemy", 300, "Royal Paladin"),
               OnlinePlayer("Friend", 200, "Elder Druid"), OnlinePlayer("Random", 100, "Sorcerer")],
              first_poll=False, now=1100)
    guild_of = {"Old Enemy": "Nexus", "New Enemy": "Nexus", "Friend": "", "Random": ""}
    built = online.build(wo, lists, WORLD, guild_of, now=1200)
    assert (built.allies, built.enemies, built.total) == (1, 2, 3 + 1)
    text = "\n".join(built.lines)
    assert text.index("**Allies**") < text.index("Friend") < text.index("**Enemies**") < text.index("Random")
    new_line = next(l for l in built.lines if "New Enemy" in l)
    old_line = next(l for l in built.lines if "Old Enemy" in l)
    assert ":zap:" in new_line and ":zap:" not in old_line  # unknown start never counts as a fresh login
    assert "`3min+`" in old_line


def test_level_filters_hide_low_players():
    wo = online.WorldOnline()
    wo.update([OnlinePlayer("Low", 10, "Knight"), OnlinePlayer("High", 500, "Knight")], first_poll=False, now=0)
    world = WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7", online_neutrals_min=100)
    built = online.build(wo, GuildLists(), world, {}, now=60)
    assert built.total == 1 and "High" in "\n".join(built.lines)


def test_level_up_flag_shows_and_clears_on_logout():
    wo = online.WorldOnline()
    wo.update([OnlinePlayer("Bubble", 101, "Knight")], first_poll=False, now=0)
    wo.set_flag("Bubble", "⬆️")
    assert "⬆️" in online.build(wo, GuildLists(), WORLD, {}, now=10).lines[0]
    wo.update([], first_poll=False, now=20)
    wo.update([OnlinePlayer("Bubble", 101, "Knight")], first_poll=False, now=30)
    assert "⬆️" not in online.build(wo, GuildLists(), WORLD, {}, now=40).lines[0]
