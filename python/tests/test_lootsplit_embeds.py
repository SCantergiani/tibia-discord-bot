"""Ported from LootSplitEmbedsSpec: how the split is written, and that it always
fits inside Discord's embed limits."""

from datetime import datetime

from tibiabot.lootsplit import HuntMember, HuntSession
from tibiabot.lootsplit_embeds import EMBED_MAX, FIELD_VALUE_MAX, MAX_FIELDS, paste, session

GOLD = ":gold:"


def member(name, balance, damage, healing, leader=False):
    return HuntMember(name, loot=0, supplies=0, balance=balance, damage=damage, healing=healing, leader=leader)


HUNT = HuntSession(
    started=datetime(2026, 9, 1, 21, 12, 0), ended=datetime(2026, 9, 1, 23, 29, 40),
    session_label="02:17h", loot_type="Leader", loot=14359954, supplies=5354392, balance=9005562,
    members=[
        member("Boss Jeremy", 62310, 14380542, 3755746),
        member("Neutrul The Wise", -748351, 17679880, 11307154),
        member("The Wingga", 9799550, 10774182, 5877463, leader=True),
        member("Violent Beams", -107947, 25228828, 3970719),
    ])


def field(embed, name):
    return next(f for f in embed.fields if f.name == name)


def crowd(balance_of, damage_of, healing_of):
    return [member(f"Party Member Number {i}", balance_of(i), damage_of(i), healing_of(i)) for i in range(1, 41)]


def test_title_counts_the_party():
    assert session(HUNT, GOLD).title == "Party Hunt Session – 4 members"


def test_headline_has_balance_split_and_rate_with_separators():
    d = session(HUNT, GOLD).description
    assert "Balance: **9,005,562**" in d
    assert "Individual balance: **2,251,390**" in d
    assert "Loot per hour: **6,258,575**" in d


def test_damage_and_healing_side_by_side_biggest_first():
    embed = session(HUNT, GOLD)
    damage, healing = field(embed, "Damage"), field(embed, "Healing")
    assert damage.inline and healing.inline
    assert damage.value.splitlines() == [
        "‣ Violent Beams (37.07%)", "‣ Neutrul The Wise (25.98%)", "‣ Boss Jeremy (21.13%)", "‣ The Wingga (15.83%)"]
    assert healing.value.splitlines() == [
        "‣ Neutrul The Wise (45.39%)", "‣ The Wingga (23.59%)", "‣ Violent Beams (15.94%)", "‣ Boss Jeremy (15.08%)"]


def test_each_transfer_is_its_own_code_block():
    transfers = field(session(HUNT, GOLD), "Transfers for The Wingga")
    assert not transfers.inline
    assert transfers.value == ("```\ntransfer 2189080 to Boss Jeremy\n```\n"
                               "```\ntransfer 2999741 to Neutrul The Wise\n```\n"
                               "```\ntransfer 2359337 to Violent Beams\n```")


def test_footer_says_length_and_start():
    assert session(HUNT, GOLD).footer.text == "02:17h hunt on 2026-09-01T21:12"


def test_square_party_says_so():
    square = HUNT.with_(balance=400, members=[member(m.name, 100, m.damage, m.healing) for m in HUNT.members])
    assert "already square" in field(session(square, GOLD), "Transfers").value


def test_solo_session_drops_split_and_transfers():
    embed = session(HUNT.with_(members=[]), GOLD)
    assert embed.title == "Hunt Session"
    assert "Individual balance" not in embed.description
    assert embed.fields == []


def test_no_damage_or_healing_leaves_those_columns_off():
    quiet = HUNT.with_(members=[member(m.name, m.balance, 0, 0, m.leader) for m in HUNT.members])
    assert [f.name for f in session(quiet, GOLD).fields] == ["Transfers for The Wingga"]


def test_unreadable_timestamps_lose_only_the_rate():
    embed = session(HUNT.with_(started=None, ended=None), GOLD)
    assert "Loot per hour" not in embed.description
    assert "Individual balance: **2,251,390**" in embed.description
    assert embed.footer.text == "02:17h hunt"


def test_implausibly_large_party_still_fits_discord_limits():
    members = crowd(lambda i: 1000 if i <= 30 else -3000, lambda i: i * 1000, lambda i: i * 500)
    embed = session(HUNT.with_(balance=0, members=members), GOLD)
    assert len(embed.fields) <= MAX_FIELDS
    assert all(len(f.value) <= FIELD_VALUE_MAX for f in embed.fields)
    assert len(embed) <= EMBED_MAX


def test_dropped_payers_are_named():
    members = crowd(lambda i: 1000 if i <= 30 else -3000, lambda i: 1, lambda i: 1)
    assert "Still to send" in field(session(HUNT.with_(balance=0, members=members), GOLD), "Transfers").value


def test_cut_column_says_how_much_it_left_out():
    members = crowd(lambda i: 0, lambda i: i * 1000, lambda i: 1)
    assert "more" in field(session(HUNT.with_(members=members), GOLD), "Damage").value


def test_paste_comes_back_byte_for_byte_as_session_txt():
    analyser = "Session data: From 2026-09-06, 09:54:08 to 2026-09-06, 10:49:12\nSession: 00:55h\n  Loot: 3,350,380\n"
    upload = paste(analyser)
    assert upload.filename == "session.txt"
    assert upload.fp.read().decode("utf-8") == analyser
