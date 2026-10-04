"""Ported from HuntAnalyserSpec: a real four-member session, every expected figure
checked against what the game itself reported for the same hunt."""

from datetime import datetime

import pytest

from tibiabot.lootsplit import HuntMember, HuntTransfer, ParseError, parse

PASTE = "\n".join([
    "Session data: From 2026-09-01, 21:12:00 to 2026-09-01, 23:29:40",
    "Session: 02:17h",
    "Loot Type: Leader",
    "Loot: 14,359,954",
    "Supplies: 5,354,392",
    "Balance: 9,005,562",
    "Boss Jeremy",
    "\tLoot: 1,654,034",
    "\tSupplies: 1,591,724",
    "\tBalance: 62,310",
    "\tDamage: 14,380,542",
    "\tHealing: 3,755,746",
    "Neutrul The Wise",
    "\tLoot: 50,000",
    "\tSupplies: 798,351",
    "\tBalance: -748,351",
    "\tDamage: 17,679,880",
    "\tHealing: 11,307,154",
    "The Wingga (Leader)",
    "\tLoot: 11,518,496",
    "\tSupplies: 1,718,946",
    "\tBalance: 9,799,550",
    "\tDamage: 10,774,182",
    "\tHealing: 5,877,463",
    "Violent Beams",
    "\tLoot: 1,137,424",
    "\tSupplies: 1,245,371",
    "\tBalance: -107,947",
    "\tDamage: 25,228,828",
    "\tHealing: 3,970,719",
])


def refusal(text: str) -> str:
    with pytest.raises(ParseError) as e:
        parse(text)
    return str(e.value)


def member(name: str, balance: int) -> HuntMember:
    return HuntMember(name, loot=0, supplies=0, balance=balance, damage=0, healing=0)


# --- reading ----------------------------------------------------------------

def test_reads_the_header_block():
    hunt = parse(PASTE)
    assert hunt.started == datetime(2026, 9, 1, 21, 12, 0)
    assert hunt.ended == datetime(2026, 9, 1, 23, 29, 40)
    assert (hunt.session_label, hunt.loot_type) == ("02:17h", "Leader")
    assert (hunt.loot, hunt.supplies, hunt.balance) == (14359954, 5354392, 9005562)


def test_reads_every_member_in_client_order():
    assert [m.name for m in parse(PASTE).members] == ["Boss Jeremy", "Neutrul The Wise", "The Wingga", "Violent Beams"]


def test_negative_balance_keeps_its_sign():
    assert next(m for m in parse(PASTE).members if m.name == "Neutrul The Wise").balance == -748351


def test_leader_marker_is_read_then_dropped_from_the_name():
    leaders = [m for m in parse(PASTE).members if m.leader]
    assert [m.name for m in leaders] == ["The Wingga"]


def test_member_figures_come_from_their_own_block():
    wingga = next(m for m in parse(PASTE).members if m.name == "The Wingga")
    assert (wingga.loot, wingga.supplies, wingga.balance, wingga.damage, wingga.healing) == \
        (11518496, 1718946, 9799550, 10774182, 5877463)


def test_paste_with_indentation_eaten_reads_the_same():
    assert parse(PASTE.replace("\t", "")) == parse(PASTE)


def test_blank_lines_and_trailing_whitespace_are_ignored():
    assert parse(PASTE.replace("\n", "  \n\n")) == parse(PASTE)


def test_market_priced_session_says_so():
    assert parse(PASTE.replace("Loot Type: Leader", "Loot Type: Market")).loot_type == "Market"


# --- refusing ---------------------------------------------------------------

def test_non_analyser_is_refused_quoting_the_paste():
    problem = refusal("how do i split loot")
    assert "Session data:" in problem and "how do i split loot" in problem


def test_empty_box_is_refused():
    refusal("   \n  ")


def test_missing_header_balance_is_refused():
    assert "Balance:" in refusal("\n".join(l for l in PASTE.split("\n") if l != "Balance: 9,005,562"))


def test_paste_cut_off_mid_member_is_refused_as_cut_off():
    problem = refusal(PASTE[:PASTE.index("\tBalance: -107,947")])
    assert "Violent Beams" in problem and "4,000 characters" in problem


def test_member_missing_a_money_line_part_way_up_is_refused_as_malformed():
    problem = refusal("\n".join(l for l in PASTE.split("\n") if l != "\tBalance: 62,310"))
    assert "Boss Jeremy" in problem and "without editing it" in problem


# --- the split --------------------------------------------------------------

def test_duration_uses_real_timestamps_not_rounded_label():
    assert parse(PASTE).duration_seconds == 8260


def test_loot_per_hour():
    assert parse(PASTE).loot_per_hour == 6258575


def test_individual_balance_floors_the_odd_gold():
    assert parse(PASTE).individual_balance == 2251390


def test_damage_shares_biggest_first():
    shares = parse(PASTE).damage_shares()
    assert [m.name for m, _ in shares] == ["Violent Beams", "Neutrul The Wise", "Boss Jeremy", "The Wingga"]
    for (_, actual), expected in zip(shares, [37.0663, 25.9756, 21.1279, 15.8296]):
        assert actual == pytest.approx(expected, abs=0.001)


def test_healing_shares_biggest_first():
    shares = parse(PASTE).healing_shares()
    assert [m.name for m, _ in shares] == ["Neutrul The Wise", "The Wingga", "Violent Beams", "Boss Jeremy"]
    for (_, actual), expected in zip(shares, [45.3901, 23.5938, 15.9396, 15.0766]):
        assert actual == pytest.approx(expected, abs=0.001)


def test_no_damage_means_no_shares():
    hunt = parse(PASTE)
    quiet = hunt.with_(members=[HuntMember(m.name, m.loot, m.supplies, m.balance, 0, 0, m.leader) for m in hunt.members])
    assert quiet.damage_shares() == [] and quiet.healing_shares() == []


def test_transfers_square_the_party_up():
    assert parse(PASTE).transfers() == [
        HuntTransfer("The Wingga", "Boss Jeremy", 2189080),
        HuntTransfer("The Wingga", "Neutrul The Wise", 2999741),
        HuntTransfer("The Wingga", "Violent Beams", 2359337),
    ]


def test_transfer_reads_as_the_game_command():
    assert parse(PASTE).transfers()[0].command == "transfer 2189080 to Boss Jeremy"


def test_everyone_ends_on_the_individual_balance():
    hunt = parse(PASTE)
    moved: dict[str, int] = {}
    for t in hunt.transfers():
        moved[t.to] = moved.get(t.to, 0) + t.amount
    for m in hunt.members:
        if not m.leader:
            assert m.balance + moved.get(m.name, 0) == hunt.individual_balance


def test_only_surplus_holders_pay_once_each():
    assert [p for p, _ in parse(PASTE).transfers_by_payer()] == ["The Wingga"]


def test_square_party_needs_no_transfers():
    hunt = parse(PASTE)
    even = hunt.with_(balance=400, members=[member(m.name, 100) for m in hunt.members])
    assert even.transfers() == []


def test_two_payers_each_get_their_own_transfers_in_party_order():
    hunt = parse(PASTE).with_(balance=4_000_000, members=[
        member("Alpha Two", 2_500_000), member("Beta Three", 1_500_000),
        member("Gamma Four", -200_000), member("Delta Five", 200_000)])
    assert hunt.individual_balance == 1_000_000
    assert hunt.transfers_by_payer() == [
        ("Alpha Two", [HuntTransfer("Alpha Two", "Gamma Four", 1_200_000),
                       HuntTransfer("Alpha Two", "Delta Five", 300_000)]),
        ("Beta Three", [HuntTransfer("Beta Three", "Delta Five", 500_000)]),
    ]


def test_solo_session_parses_and_splits_with_nobody():
    hunt = parse("\n".join([
        "Session data: From 2026-09-01, 21:12:00 to 2026-09-01, 22:12:00",
        "Session: 01:00h", "Loot Type: Leader", "Loot: 1,000,000", "Supplies: 400,000", "Balance: 600,000"]))
    assert hunt.members == [] and hunt.transfers() == []
    assert hunt.loot_per_hour == 1_000_000
    assert hunt.individual_balance == 600_000


def test_unreadable_timestamps_cost_only_the_hourly_rate():
    hunt = parse(PASTE.replace("2026-09-01, 21:12:00", "yesterday evening"))
    assert hunt.started is None and hunt.loot_per_hour is None
    assert len(hunt.transfers()) == 3
