from datetime import date, datetime, timedelta, timezone

from tibiabot import deaths, serversave
from tibiabot.db.repos import WorldConfig
from tibiabot.lists.models import GuildLists, ListedGuild, ListedPlayer
from tibiabot.tibiadata.models import Character, Death, Killer

NOW = datetime(2026, 10, 4, 20, 0, tzinfo=timezone.utc)
WORLD = WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7")


def victim(name="Victim", guild=None, vocation="Elite Knight"):
    return Character(name=name, level=300, vocation=vocation, world="Inabra", sex="male", guild_name=guild,
                     guild_rank="Member" if guild else None, former_names=[], former_worlds=[], last_login=None,
                     account_status="", traded=False, deletion_date=None, comment="")


def died(*killers: Killer, level=300, minutes_ago=2):
    return Death(NOW - timedelta(minutes=minutes_ago), level, list(killers), [], "")


def creature(name):
    return Killer(name, False, False, "")


def player(name, summon=""):
    return Killer(name, True, False, summon)


def lists(**kw):
    l = GuildLists()
    for name in kw.get("hunted_players", []):
        l.hunted_players[name] = ListedPlayer(name)
    for name in kw.get("allied_players", []):
        l.allied_players[name] = ListedPlayer(name)
    for name in kw.get("hunted_guilds", []):
        l.hunted_guilds[name] = ListedGuild(name)
    for name in kw.get("allied_guilds", []):
        l.allied_guilds[name] = ListedGuild(name)
    return l


def test_neutral_pve_death():
    post = deaths.build_death(victim(), died(creature("dragon lord")), GuildLists(), WORLD, {})
    assert post.color == deaths.NEUTRAL and post.poke == ""
    assert "Died <t:" in post.description and "at level 300" in post.description
    assert "by a **dragon lord**." in post.description
    assert post.title == ":shield: Victim :shield:"


def test_enemy_death_is_green_and_wants_a_fullbless_ping():
    post = deaths.build_death(victim(guild="Nexus"), died(creature("dragon")), lists(hunted_guilds=["nexus"]), WORLD, {})
    assert post.color == deaths.ENEMY and post.poke == "fullbless"
    assert post.side_label == "🟥 ENEMY DIED"
    assert "*Member* of the [Nexus]" in post.description


def test_rare_boss_overrides_everything():
    post = deaths.build_death(victim(), died(creature("the frog prince")), GuildLists(), WORLD, {})
    assert post.color == deaths.NEMESIS and post.poke == "nemesis"


def test_ally_killed_by_players_pings_pvp_and_lists_exivas_highest_first():
    world = WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7", exiva_list="true")
    post = deaths.build_death(victim(), died(player("Low Guy"), player("High Guy"), creature("dragon")),
                              lists(allied_players=["victim"]), world, {"low guy": 100, "high guy": 500})
    assert post.color == deaths.ALLY and post.poke == "allypk"
    assert post.side_label == "🟩 ALLY DIED"
    assert "Killed <t:" in post.description
    assert "**[Low Guy [100]](" in post.description and "**[High Guy [500]](" in post.description
    exivas = [line for line in post.description.splitlines() if line.startswith("exiva ")]
    assert '"High Guy"' in exivas[0] and '"Low Guy"' in exivas[1]
    assert post.frag_killers == ["Low Guy", "High Guy"]


def test_exiva_count_caps_the_list_and_zero_lists_everyone():
    names = [f"Killer {i}" for i in range(8)]
    levels = {n.lower(): 100 + i for i, n in enumerate(names)}

    def exivas(count: int) -> list[str]:
        world = WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7", exiva_list="true",
                            exiva_count=count)
        post = deaths.build_death(victim(), died(*(player(n) for n in names)), lists(allied_players=["victim"]),
                                  world, levels)
        return [line for line in post.description.splitlines() if line.startswith("exiva ")]

    assert exivas(3) == ['exiva "Killer 7"', 'exiva "Killer 6"', 'exiva "Killer 5"']
    assert len(exivas(0)) == 8


def test_no_exiva_list_when_the_setting_is_off():
    post = deaths.build_death(victim(), died(player("Killer")), lists(allied_players=["victim"]), WORLD, {})
    assert "exiva" not in post.description


def test_enemy_killed_by_players_asks_for_a_screenshot_not_a_ping():
    post = deaths.build_death(victim(), died(player("Our Guy")), lists(hunted_players=["victim"]), WORLD, {})
    assert post.poke == "screenshot" and post.color == deaths.ENEMY


def test_neutral_pvp_is_bone_white_with_no_ping():
    post = deaths.build_death(victim(), died(player("Someone")), GuildLists(), WORLD, {})
    assert post.color == deaths.PVP_NEUTRAL and post.poke == ""


def test_summon_kill_names_the_summoner_with_their_level():
    post = deaths.build_death(victim(), died(player("Bubble", summon="fire elemental")), GuildLists(), WORLD,
                              {"bubble": 250})
    assert "**fire elemental of [Bubble [250]](" in post.description
    assert post.frag_killers == ["Bubble"]


def test_self_entry_is_ignored_and_no_killers_is_suicide():
    post = deaths.build_death(victim(), died(player("Victim")), GuildLists(), WORLD, {})
    assert "`suicide`" in post.description and post.thumbnail == deaths.creatures.SUICIDE_THUMBNAIL


def test_visibility_follows_the_colour_bucket():
    hidden_enemies = WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7", show_enemies_deaths="false")
    enemy = deaths.build_death(victim(), died(creature("rat")), lists(hunted_players=["victim"]), hidden_enemies, {})
    neutral = deaths.build_death(victim(), died(creature("rat")), GuildLists(), hidden_enemies, {})
    assert not enemy.visible(hidden_enemies) and neutral.visible(hidden_enemies)


def test_level_line_and_filters():
    up = deaths.LevelUp(victim(guild="Nexus"), 301, "Elite Knight")
    line, rel = deaths.level_line(up, lists(hunted_guilds=["nexus"]))
    assert "advanced to" in line and "level **301**" in line and rel.side == "enemy"
    hide_enemies = WorldConfig("Inabra", "1", "0", "0", "2", "3", "4", "5", "6", "7", show_enemies_levels="false")
    assert not deaths.level_visible(rel, 301, hide_enemies)
    assert deaths.level_visible(rel, 301, WORLD)
    neutral = deaths.Relation(False, False, False, False)
    assert not deaths.level_visible(neutral, 5, WORLD)  # below levels_min 8


def test_ally_guild_wins_over_hunted_player_for_the_level_side():
    rel = deaths.relation_of(lists(allied_guilds=["friends"], hunted_players=["victim"]), "Victim", "Friends")
    assert rel.side == "ally"


def test_server_save_day():
    # 09:59 Berlin belongs to the previous day; 10:00 opens a new one.
    assert serversave.save_day(datetime(2026, 10, 4, 7, 59, tzinfo=timezone.utc)) == date(2026, 10, 3)
    assert serversave.save_day(datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)) == date(2026, 10, 4)
