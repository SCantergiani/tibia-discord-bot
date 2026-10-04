"""Ported from KillersSpec."""

from tibiabot.killers import (article, exiva_targets, join_natural, join_within, level_lookup_names, parse_summon,
                              source_article, summon_behind)


def test_parse_summon():
    assert parse_summon("fire elemental of Violent Beams") == ("fire elemental", "Violent Beams")
    assert parse_summon("a war golem of Xyz") == ("a war golem", "Xyz")
    assert parse_summon("Knight of Flame") is None
    assert parse_summon("Lord of the Elements") is None
    assert parse_summon("a dragon lord") is None and parse_summon("Bubble") is None
    assert parse_summon("energy elemental of Sir of Camelot") == ("energy elemental", "Sir of Camelot")


def test_summon_behind():
    assert summon_behind("Beams of Justice", "fire elemental") == ("fire elemental", "Beams of Justice")
    assert summon_behind("Beams of Justice", "") is None
    assert summon_behind("Beams of Justice", "   ") is None
    assert summon_behind("Bubble", None) is None
    assert summon_behind("fire elemental of Violent Beams", "") == ("fire elemental", "Violent Beams")
    assert summon_behind("Knight of Flame", "") is None


def test_articles():
    assert [article(n) for n in ("energy elemental", "orshabaal", "dragon lord", "fire elemental")] == \
        ["an", "an", "a", "a"]
    assert [source_article(n) for n in ("energy", "fire", "a trap", "life drain")] == ["", "", "", ""]
    assert source_article("dragon lord") == "a " and source_article("orc berserker") == "an "


def test_level_lookup_names():
    assert level_lookup_names("Victim", [("Bubble", True), ("a dragon", False)]) == ["Bubble"]
    assert level_lookup_names("Victim", [("Victim", True), ("Bubble", True)]) == ["Bubble"]
    assert level_lookup_names("Victim", [("fire elemental of Bubble", True)]) == ["Bubble"]
    assert level_lookup_names("Victim", [("Knight of Flame", True)]) == ["Knight of Flame"]
    assert level_lookup_names("Victim", [("energy", False), ("drowning", False)]) == []


def test_join_natural():
    assert join_natural([]) == "" and join_natural(["a dragon"]) == "a dragon"
    assert join_natural(["a dragon", "a dragon lord"]) == "a dragon and a dragon lord"
    assert join_natural(["a", "b", "c"]) == "a, b and c"


def test_join_within():
    assert join_within(["a", "b", "c"], 4065) == "a, b and c"
    assert join_within(["aaaa"] * 5, 30) == "aaaa, aaaa, aaaa and 2 more"
    assert join_within(["aaaa"] * 5, 24) == "aaaa, aaaa and 3 more"
    assert join_within(["a" * 50], 20) == "1 killer"
    assert join_within(["a" * 50] * 3, 20) == "3 killers"
    fitted = join_within([f"**[Player{i}](x)**" for i in range(100)], 500)
    shown, hidden = fitted.rsplit(" and ", 1)
    assert len(shown.split(", ")) + int(hidden.split()[0]) == 100


def test_exiva_targets():
    killers = [("A", 100), ("B", 500), ("C", 300), ("D", 200), ("E", 400), ("F", 50)]
    assert exiva_targets(killers) == ["B", "E", "C", "D", "A"]
    assert exiva_targets([("Low", 80), ("High", 410)]) == ["High", "Low"]
    assert exiva_targets([]) == []
    assert exiva_targets([("Bubble", None), ("Other", 300), ("Bubble", 400)]) == ["Bubble", "Other"]
    assert exiva_targets([("Unknown", None), ("Known", 80)]) == ["Known", "Unknown"]
    assert exiva_targets([("X", 10), ("Y", 10)]) == ["X", "Y"]
