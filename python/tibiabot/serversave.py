"""Tibia's day turns over at server save, 10:00 Berlin time."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
SERVER_SAVE = time(10, 0)


def last_server_save(now: datetime) -> datetime:
    berlin = now.astimezone(BERLIN)
    todays = datetime.combine(berlin.date(), SERVER_SAVE, tzinfo=BERLIN)
    return todays - timedelta(days=1) if berlin < todays else todays


def next_server_save(now: datetime) -> datetime:
    return last_server_save(now) + timedelta(days=1)


def save_day(when: datetime) -> date:
    """The game day `when` belongs to, named by the date of the save that opened it."""
    return last_server_save(when).date()
