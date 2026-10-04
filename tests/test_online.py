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
    assert online.base_name("📈・ᴏɴʟɪɴᴇ・🤍3💀2⚡", "online") == "📈・ᴏɴʟɪɴᴇ"
    assert online.base_name("📈・ᴏɴʟɪɴᴇ・💀2", "online") == "📈・ᴏɴʟɪɴᴇ"
    assert online.base_name("📈・ᴏɴʟɪɴᴇ", "online") == "📈・ᴏɴʟɪɴᴇ"
    assert online.base_name("online-42", "online") == "online"
    assert online.base_name("ɴᴇᴍᴇsɪs-5", "enemies") == "ɴᴇᴍᴇsɪs"
    assert online.base_name("allies", "allies") == "allies"
    assert online.base_name("my-cool-list-99", "online") == "my-cool-list"
    assert online.base_name("online-⚠️", "online") == "online"


def test_channel_name_carries_the_count_and_mass_log():
    assert online.channel_name("🤍・ᴀʟʟɪᴇs", 3) == "🤍・ᴀʟʟɪᴇs・3"
    assert online.channel_name("⚔️・ᴇɴᴇᴍɪᴇs", 0) == "⚔️・ᴇɴᴇᴍɪᴇs・0"
    assert online.channel_name("⚔️・ᴇɴᴇᴍɪᴇs", 6, masslog=True) == "⚔️・ᴇɴᴇᴍɪᴇs・6⚡"
    name = online.channel_name("⚔️・ᴇɴᴇᴍɪᴇs", 12, masslog=True)
    assert online.channel_name(online.base_name(name, "enemies"), 2) == "⚔️・ᴇɴᴇᴍɪᴇs・2"
    assert online.base_name("🤍・ᴀʟʟɪᴇs", "allies") == "🤍・ᴀʟʟɪᴇs"


def test_masslog_needs_five_logins():
    assert online.is_masslog(5) and online.is_masslog(12)
    assert not online.is_masslog(4) and not online.is_masslog(0)
    assert online.is_masslog(3, min_enemies=3)


# --- grouping ---------------------------------------------------------------

def test_group_by_guild_biggest_first_guildless_last():
    rows = [("", "a"), ("Small", "b"), ("Big", "c"), ("Big", "d"), ("", "e"), ("", "f")]
    assert online.group_by_guild(rows) == [("Big", ["c", "d"]), ("Small", ["b"]), ("", ["a", "e", "f"])]
    assert online.group_by_guild([]) == []


def test_with_headers():
    lines = online.with_headers([("Big", ["c"]), ("", ["a"])], lambda n: f"### Others {n}")
    assert lines[0].startswith("### [Big](") and lines[0].endswith(" 1")
    assert lines[1:] == ["c", "### Others 1", "a"]


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

def test_build_lists_only_allies_and_enemies_grouped_by_guild():
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
    assert (built.allies, built.enemies, built.total) == (1, 2, 3)
    text = "\n".join(built.lines)
    assert "Random" not in text
    assert built.lines[0].startswith("## ") and "Allies 1" in built.lines[0]
    assert text.index("Friend") < text.index("Enemies 2") < text.index("### [Nexus]") < text.index("New Enemy")
    new_line = next(l for l in built.lines if "New Enemy" in l)
    old_line = next(l for l in built.lines if "Old Enemy" in l)
    assert ":zap:" in new_line and ":zap:" not in old_line  # unknown start never counts as a fresh login
    assert "`3min+`" in old_line


def test_allies_and_enemies_get_separate_lists():
    lists = GuildLists()
    lists.hunted_players["foe"] = ListedPlayer("foe")
    lists.allied_players["friend"] = ListedPlayer("friend")
    wo = online.WorldOnline()
    wo.update([OnlinePlayer("Foe", 300, "Knight"), OnlinePlayer("Friend", 200, "Druid")], first_poll=False, now=0)
    built = online.build(wo, lists, WORLD, {}, now=60)
    assert "Allies 1" in built.ally_lines[0] and not any("Foe" in l for l in built.ally_lines)
    assert "Enemies 1" in built.enemy_lines[0] and not any("Friend" in l for l in built.enemy_lines)
    assert built.lines == built.ally_lines + built.enemy_lines


def test_nobody_listed_online_gives_an_empty_list():
    wo = online.WorldOnline()
    wo.update([OnlinePlayer("Random", 100, "Knight")], first_poll=False, now=0)
    assert online.build(wo, GuildLists(), WORLD, {}, now=60).lines == []


def test_level_filters_hide_low_enemies():
    lists = GuildLists()
    lists.hunted_players["low"] = ListedPlayer("low")
    lists.hunted_players["high"] = ListedPlayer("high")
    wo = online.WorldOnline()
    wo.update([OnlinePlayer("Low", 10, "Knight"), OnlinePlayer("High", 500, "Knight")], first_poll=False, now=0)
    world = WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7", online_enemies_min=100)
    built = online.build(wo, lists, world, {}, now=60)
    assert built.enemies == 1 and "High" in "\n".join(built.lines) and "Low" not in "\n".join(built.lines)


def test_level_up_flag_shows_and_clears_on_logout():
    lists = GuildLists()
    lists.allied_players["bubble"] = ListedPlayer("bubble")
    wo = online.WorldOnline()
    wo.update([OnlinePlayer("Bubble", 101, "Knight")], first_poll=False, now=0)
    wo.set_flag("Bubble", "⬆️")
    line = lambda: next(l for l in online.build(wo, lists, WORLD, {}, now=40).lines if "Bubble" in l)
    assert "⬆️" in line()
    wo.update([], first_poll=False, now=20)
    wo.update([OnlinePlayer("Bubble", 101, "Knight")], first_poll=False, now=30)
    assert "⬆️" not in line()


# --- mass log alert ---------------------------------------------------------

from dataclasses import replace  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import discord  # noqa: E402

from tibiabot.cogs.online import OnlineCog  # noqa: E402
from tibiabot.cogs.settings import role_panel  # noqa: E402


def test_masslog_mode_reads_the_column():
    assert online.masslog_mode(replace(WORLD, masslog_role="123")) == "role"
    assert online.masslog_mode(replace(WORLD, masslog_role="everyone")) == "everyone"
    assert online.masslog_mode(replace(WORLD, masslog_role="0")) == "off"


def _enemies_logging_in(count: int, at: float) -> tuple[online.WorldOnline, GuildLists, dict[str, str]]:
    lists = GuildLists()
    lists.hunted_guilds["nexus"] = ListedGuild("nexus")
    wo = online.WorldOnline()
    wo.update([], first_poll=True, now=0)
    names = [f"Enemy {i}" for i in range(count)]
    wo.update([OnlinePlayer(n, 300, "Knight") for n in names], first_poll=False, now=at)
    return wo, lists, {n: "Nexus" for n in names}


def test_five_enemies_within_five_minutes_is_a_mass_log():
    wo, lists, guild_of = _enemies_logging_in(5, at=60)
    built = online.build(wo, lists, WORLD, guild_of, now=120)
    assert built.masslog and len(built.fresh_enemies) == 5


def test_four_enemies_is_not_a_mass_log():
    wo, lists, guild_of = _enemies_logging_in(4, at=60)
    built = online.build(wo, lists, WORLD, guild_of, now=120)
    assert not built.masslog and len(built.fresh_enemies) == 4


def test_logins_older_than_the_window_dont_count():
    wo, lists, guild_of = _enemies_logging_in(6, at=60)
    built = online.build(wo, lists, WORLD, guild_of, now=60 + 5 * 60)
    assert not built.masslog and built.fresh_enemies == []
    assert ":zap:" in "\n".join(built.lines)  # still marked as a recent login in the list
    assert online.build(wo, lists, WORLD, guild_of, now=60 + 5 * 60, masslog_window=10 * 60).masslog


async def test_role_panel_has_a_masslog_button_only_in_role_mode():
    def ids(world):
        _, view = role_panel(world)
        return [c["custom_id"] for r in view.to_components() for c in r["components"]]
    assert "role:masslog_role:Inabra" in ids(replace(WORLD, masslog_role="123"))
    assert "role:masslog_role:Inabra" not in ids(replace(WORLD, masslog_role="everyone"))


class FakeChannel(discord.TextChannel):
    def __init__(self):  # noqa: D401 - stands in for a real channel
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


async def test_alert_pings_the_chosen_audience_once_per_cooldown():
    channel = FakeChannel()
    role = SimpleNamespace(mention="<@&123>", id=123)
    guild = SimpleNamespace(id=1, get_channel=lambda _: channel, get_role=lambda _: role)
    bot = SimpleNamespace(settings=SimpleNamespace(masslog_minutes=5), pollers=SimpleNamespace(listeners=[]),
                          state=SimpleNamespace(guild=lambda _: SimpleNamespace(worlds={})))
    cog = OnlineCog(bot)
    built = online.OnlineList([], [], 0, 5, 5, True, ["a", "b", "c", "d"])
    await cog._masslog_alert(guild, replace(WORLD, masslog_role="123"), built)
    await cog._masslog_alert(guild, replace(WORLD, masslog_role="123"), built)
    assert len(channel.sent) == 1 and channel.sent[0][0] == "<@&123>"
    assert "**4** enemies logged in" in channel.sent[0][1]["embed"].description
    everyone = FakeChannel()
    guild2 = SimpleNamespace(id=2, get_channel=lambda _: everyone, get_role=lambda _: None)
    await cog._masslog_alert(guild2, replace(WORLD, masslog_role="everyone"), built)
    assert everyone.sent[0][0] == "@everyone" and everyone.sent[0][1]["allowed_mentions"].everyone
    off = FakeChannel()
    guild3 = SimpleNamespace(id=3, get_channel=lambda _: off, get_role=lambda _: None)
    await cog._masslog_alert(guild3, replace(WORLD, masslog_role="0"), built)
    assert off.sent == []


async def test_masslog_can_ping_the_member_role():
    assert online.masslog_mode(replace(WORLD, masslog_role="members")) == "members"
    channel = FakeChannel()
    member_role = SimpleNamespace(mention="<@&999>", id=999)
    guild = SimpleNamespace(id=5, get_channel=lambda _: channel, get_role=lambda rid: member_role if rid == 999 else None)
    info = SimpleNamespace(member_role="999")
    bot = SimpleNamespace(settings=SimpleNamespace(masslog_minutes=5), pollers=SimpleNamespace(listeners=[]),
                          state=SimpleNamespace(guild=lambda _: SimpleNamespace(info=info, worlds={})))
    cog = OnlineCog(bot)
    await cog._masslog_alert(guild, replace(WORLD, masslog_role="members"), online.OnlineList([], [], 0, 5, 5, True, ["a"]))
    assert channel.sent[0][0] == "<@&999>"


def test_role_panel_names_the_member_role_for_mass_logs():
    embed, view = role_panel(replace(WORLD, masslog_role="members"), member_role="999")
    assert "Mass logs ping <@&999>" in embed.description
    assert "role:masslog_role:Inabra" not in [c["custom_id"] for r in view.to_components() for c in r["components"]]


async def test_mass_log_alert_goes_to_the_enemies_channel():
    deaths, enemies = FakeChannel(), FakeChannel()
    world = replace(WORLD, masslog_role="everyone", enemies_channel="9")
    guild = SimpleNamespace(id=7, get_channel=lambda cid: enemies if cid == 9 else deaths, get_role=lambda _: None)
    bot = SimpleNamespace(settings=SimpleNamespace(masslog_minutes=5), pollers=SimpleNamespace(listeners=[]),
                          state=SimpleNamespace(guild=lambda _: SimpleNamespace(worlds={})))
    await OnlineCog(bot)._masslog_alert(guild, world, online.OnlineList([], ["x"], 0, 6, 6, True, ["a"] * 5))
    assert len(enemies.sent) == 1 and deaths.sent == []
    assert "**6** online" in enemies.sent[0][1]["embed"].description


class FakeCache:
    def __init__(self, last=None):
        self.last = last
        self.writes = 0

    async def fetchval(self, *_):
        return self.last

    async def execute(self, *_):
        self.writes += 1
        self.last = datetime.now(timezone.utc).replace(tzinfo=None)


async def test_rename_waits_out_discords_limit_then_uses_the_latest_name():
    from tibiabot.cogs import online as cog_module
    cache = FakeCache(last=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2))
    cog = OnlineCog(SimpleNamespace(pollers=SimpleNamespace(listeners=[]), db=SimpleNamespace(cache=cache)))
    renamed, slept = [], []

    async def edit(name):
        renamed.append(name)
        channel.name = name
    channel = SimpleNamespace(id=1, name="⚔️・ᴇɴᴇᴍɪᴇs・1", edit=edit)

    async def sleep(seconds):
        slept.append(seconds)
        cog._wanted_name[1] = "⚔️・ᴇɴᴇᴍɪᴇs・5⚡"  # more logged in while waiting
        cache.last -= cog_module.RENAME_COOLDOWN

    cog._wanted_name[1] = "⚔️・ᴇɴᴇᴍɪᴇs・3"
    await cog._rename(channel, "Inabra", sleep=sleep)
    assert renamed == ["⚔️・ᴇɴᴇᴍɪᴇs・5⚡"] and cache.writes == 1
    assert 175 < slept[0] <= 185  # 5 min 5 s minus the 2 min since the last rename


async def test_enemies_then_allies_lead_the_category():
    moves = []

    def chan(name):
        async def move(**kwargs):
            moves.append((name, kwargs.get("beginning"), getattr(kwargs.get("after"), "name", None)))
        return SimpleNamespace(name=name, category_id=1, move=move)
    enemies, allies, deaths = chan("enemies"), chan("allies"), chan("deaths")
    category = SimpleNamespace(id=1, guild=SimpleNamespace(id=1), text_channels=[allies, deaths, enemies])
    allies.category = category
    await OnlineCog._order(enemies, allies)
    assert moves == [("enemies", True, None), ("allies", None, "enemies")]
    moves.clear()
    category.text_channels = [enemies, allies, deaths]
    await OnlineCog._order(enemies, allies)
    assert moves == []
