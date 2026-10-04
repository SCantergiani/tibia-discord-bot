"""Ported from NameListSpec, ListTagsSpec and ListReviewSpec."""

from tibiabot.lists.models import (GONE, TRADED, ListedPlayer, find_tag, moved_world, parse_names, review,
                                   review_missing, scheduled_for_deletion, tag_mark)

TRACKED = {"Antica", "Belobra"}


def entry(traded_when_added=False, flagged=""):
    return ListedPlayer("bubble", traded_when_added=traded_when_added, flagged_reason=flagged)


# --- names ------------------------------------------------------------------

def test_one_name_per_line():
    assert parse_names("Bubble\nEternal Oblivion\nCharm") == ["Bubble", "Eternal Oblivion", "Charm"]


def test_blank_lines_and_whitespace_dropped():
    assert parse_names("  Bubble  \n\n\n   \n Charm \n") == ["Bubble", "Charm"]


def test_commas_semicolons_tabs_separate():
    assert parse_names("Bubble, Charm; Vidar\tArieswar") == ["Bubble", "Charm", "Vidar", "Arieswar"]


def test_bullets_and_numbering_stripped():
    assert parse_names("- Bubble\n* Charm\n1. Vidar\n12) Arieswar\n• Zyzz") == \
        ["Bubble", "Charm", "Vidar", "Arieswar", "Zyzz"]


def test_hyphen_inside_name_survives():
    assert parse_names("Kharon-Ur\n- Kharon-Ur II") == ["Kharon-Ur", "Kharon-Ur II"]


def test_quotes_backticks_bold_stripped():
    assert parse_names('"Bubble"\n`Charm`\n**Vidar**') == ["Bubble", "Charm", "Vidar"]


def test_duplicates_dropped_keeping_first_spelling():
    assert parse_names("Bubble\nbubble\nBUBBLE\nCharm") == ["Bubble", "Charm"]


def test_implausible_lengths_dropped():
    assert parse_names("A\nBubble\n" + "x" * 30) == ["Bubble"]


def test_empty_and_none():
    assert parse_names("") == [] and parse_names(None) == []


# --- tags -------------------------------------------------------------------

def test_tags():
    assert find_tag("BOT").label == "Bot"
    assert find_tag("none") is None and find_tag("") is None and find_tag("nonsense") is None
    assert tag_mark("rat") == " 🐀" and tag_mark("") == ""


# --- review -----------------------------------------------------------------

def test_traded_after_being_added_is_flagged():
    assert review(entry(), True, "Antica", TRACKED) == TRADED


def test_already_traded_when_added_is_never_flagged_for_it():
    assert review(entry(traded_when_added=True), True, "Antica", TRACKED) is None


def test_not_traded_not_flagged():
    assert review(entry(), False, "Antica", TRACKED) is None


def test_untracked_world_is_flagged():
    assert review(entry(), False, "Vunira", TRACKED) == moved_world("Vunira")


def test_any_tracked_world_ignoring_case_is_fine():
    assert review(entry(), False, "Belobra", TRACKED) is None
    assert review(entry(), False, "aNTiCa", TRACKED) is None


def test_empty_world_or_no_tracked_worlds_flags_nobody():
    assert review(entry(), False, "", TRACKED) is None
    assert review(entry(), False, "Vunira", set()) is None


def test_already_flagged_is_not_flagged_again():
    assert review(entry(flagged="traded"), True, "Vunira", TRACKED) is None
    assert review_missing(entry(flagged="traded")) is None


def test_traded_wins_over_world_move():
    assert review(entry(), True, "Vunira", TRACKED) == TRADED


def test_reasons_are_the_stored_strings():
    assert (TRADED.reason, moved_world("x").reason, GONE.reason, scheduled_for_deletion("d").reason) == \
        ("traded", "world", "gone", "deletion")


def test_missing_name_is_gone():
    assert review_missing(entry()) == GONE


def test_deletion_outranks_everything():
    assert review(entry(), True, "Vunira", TRACKED, "2026-10-01T00:00:00Z") == \
        scheduled_for_deletion("2026-10-01T00:00:00Z")
    assert review(entry(), False, "Antica", TRACKED, "") is None
