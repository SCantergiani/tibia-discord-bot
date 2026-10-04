import re

from tibiabot.cogs.watchdog import room_name


def test_room_names_are_url_safe_unguessable_and_carry_the_hint():
    name = room_name("Library — Asura Palace!")
    assert re.fullmatch(r"popaco-library-asura-palace-[0-9a-f]{8}", name)
    assert re.fullmatch(r"popaco-[0-9a-f]{8}", room_name())
    assert room_name() != room_name()
