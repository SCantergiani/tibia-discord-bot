"""Ported from BossPredictorSpec, plus the catalogue and the post's wording."""

from datetime import date, timedelta

from tibiabot import bosses
from tibiabot.cogs.statistics import bosses_embed, timing

TODAY = date(2026, 10, 4)


def seen(days_ago: int) -> date:
    return TODAY - timedelta(days=days_ago)


def chance(days_since: int, lo: int = 12, hi: int = 28) -> bosses.BossChance:
    return bosses.chance_for(TODAY, seen(days_since), lo, hi)


def boss(predict=True, spawn_points=1, lo=12, hi=28):
    return bosses.Boss("Test Boss", None, predict, lo, hi, spawn_points, "")


def test_catalogue_loads():
    names = {b.name for b in bosses.catalogue()}
    assert len(bosses.catalogue()) == 74 and "Ferumbras" in names


def test_killed_today_is_not_due():
    assert chance(0).chance == bosses.NONE


def test_short_of_the_window_is_not_due():
    assert chance(5).chance == bosses.NONE and chance(10).chance == bosses.NONE


def test_day_before_the_window_is_low():
    assert chance(11).chance == bosses.LOW


def test_inside_the_window_is_high():
    assert [chance(d).chance for d in (12, 20, 28)] == [bosses.HIGH] * 3


def test_first_window_is_always_shown():
    c = chance(5)
    assert (c.window_min, c.window_max) == (12, 28)


def test_wide_window_tiles_so_past_opening_it_is_always_due():
    c = chance(30)
    assert c.chance == bosses.HIGH and c.window_min == 12 and c.window_max is None
    assert chance(400).window_max is None


def test_narrow_window_counts_towards_a_later_one():
    c = bosses.chance_for(TODAY, seen(340), 161, 175)
    assert (c.chance, c.window_min, c.window_max, c.days_since) == (bosses.HIGH, 322, 350, 340)
    assert bosses.chance_for(TODAY, seen(200), 161, 175).chance == bosses.NONE


def test_long_cycle_boss():
    assert bosses.chance_for(TODAY, seen(100), 161, 175).chance == bosses.NONE
    assert bosses.chance_for(TODAY, seen(165), 161, 175).chance == bosses.HIGH


def test_hand_edited_catalogue_cannot_divide_by_zero():
    for days, lo, hi in ((5, 1, 1), (30, 10, 10), (0, 0, 0)):
        bosses.chance_for(TODAY, seen(days), lo, hi)


def test_future_sighting_gives_no_negative_days():
    assert bosses.chance_for(TODAY, TODAY + timedelta(days=3), 12, 28).days_since == 0


def test_predict_rules():
    assert bosses.predict(boss(), [], TODAY) is None
    assert bosses.predict(boss(predict=False), [(seen(20), 1)], TODAY) is None
    p = bosses.predict(boss(), [(seen(20), 1)], TODAY)
    assert p.best == bosses.HIGH and p.days_since == 20
    p = bosses.predict(boss(), [(seen(2), 1), (seen(20), 1)], TODAY)
    assert p.days_since == 2 and len(p.chances) == 1


def test_multi_spawn_bosses_track_each_spawn_point():
    p = bosses.predict(boss(spawn_points=4), [(seen(2), 1), (seen(20), 1), (seen(30), 1), (seen(40), 1)], TODAY)
    assert len(p.chances) == 4 and p.best == bosses.HIGH and p.days_since == 2
    p = bosses.predict(boss(spawn_points=4), [(seen(3), 3), (seen(40), 1)], TODAY)
    assert sum(c.days_since == 3 for c in p.chances) == 3 and sum(c.days_since == 40 for c in p.chances) == 1
    assert len(bosses.predict(boss(spawn_points=4), [(seen(20), 1)], TODAY).chances) == 1


def test_awaiting_first_sighting_counts_predictable_bosses_never_seen():
    predictable = sum(1 for b in bosses.catalogue() if b.predict)
    assert bosses.awaiting_first_sighting({}) == predictable
    first = next(b for b in bosses.catalogue() if b.predict)
    assert bosses.awaiting_first_sighting({first.race.lower(): [(TODAY, 1)]}) == predictable - 1


def test_timing_wording():
    assert timing(chance(5)).startswith("opens <t:")
    assert timing(chance(20)).startswith("window closes <t:")
    assert timing(chance(30)).startswith("overdue since <t:")


def test_bosses_embed_lists_due_bosses_and_explains_an_empty_history():
    p = bosses.predict(boss(), [(seen(20), 1)], TODAY)
    embed = bosses_embed("Inabra", [p], 3)
    assert ":green_circle:" in embed.description and "**Test Boss**" in embed.description
    assert embed.footer.text.startswith("3 boss(es)")
    assert "Not enough history yet" in bosses_embed("Inabra", [], 57).description
