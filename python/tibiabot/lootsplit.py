"""Reads a Tibia party hunt analyser paste and works out who pays whom.

The paste is a header block then one block per member::

    Session data: From 2026-09-01, 21:12:00 to 2026-09-01, 23:29:40
    Session: 02:17h
    Loot Type: Leader
    Loot: 14,359,954
    Supplies: 5,354,392
    Balance: 9,005,562
    The Wingga (Leader)
        Loot: 11,518,496
        ...

Indentation is not trusted (a clipboard and a Discord textarea both eat it): a
line is a value if it reads `<known key>: <number>`, anything else starts a
member. Tibia names cannot contain a colon, so nothing collides.

All division floors, like the game client: the leftover (at most one gold per
member) stays with whoever holds it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime

HEADER_KEYS = {"session", "loot type", "loot", "supplies", "balance"}
MEMBER_KEYS = {"loot", "supplies", "balance", "damage", "healing"}
MONEY_KEYS = {"loot", "supplies", "balance"}
_SESSION_DATA = re.compile(r"^session data:\s*from\s+(.+?)\s+to\s+(.+?)\s*$", re.IGNORECASE)
_LEADER = re.compile(r"\s*\(leader\)\s*$", re.IGNORECASE)
_STAMP = "%Y-%m-%d, %H:%M:%S"


class ParseError(ValueError):
    """Carries a sentence meant for the person who pasted."""


@dataclass(frozen=True)
class HuntMember:
    name: str
    loot: int
    supplies: int
    balance: int
    damage: int
    healing: int
    leader: bool = False


@dataclass(frozen=True)
class HuntTransfer:
    sender: str
    to: str
    amount: int

    @property
    def command(self) -> str:
        """Exactly what gets typed in-game: no thousands separators."""
        return f"transfer {self.amount} to {self.to}"


@dataclass(frozen=True)
class HuntSession:
    started: datetime | None
    ended: datetime | None
    session_label: str
    loot_type: str
    loot: int
    supplies: int
    balance: int
    members: list[HuntMember] = field(default_factory=list)

    def with_(self, **changes) -> HuntSession:
        return replace(self, **changes)

    @property
    def duration_seconds(self) -> int | None:
        """From the header timestamps, not the `Session:` label, which drops seconds."""
        if self.started and self.ended:
            seconds = int((self.ended - self.started).total_seconds())
            return seconds if seconds > 0 else None
        return None

    @property
    def loot_per_hour(self) -> int | None:
        seconds = self.duration_seconds
        return self.loot * 3600 // seconds if seconds else None

    @property
    def individual_balance(self) -> int:
        return self.balance // len(self.members) if self.members else self.balance

    def damage_shares(self) -> list[tuple[HuntMember, float]]:
        return self._shares(lambda m: m.damage)

    def healing_shares(self) -> list[tuple[HuntMember, float]]:
        return self._shares(lambda m: m.healing)

    def _shares(self, of) -> list[tuple[HuntMember, float]]:
        total = sum(of(m) for m in self.members)
        if total <= 0:
            return []
        # sorted() is stable, so equal shares keep paste order.
        return sorted(((m, of(m) * 100.0 / total) for m in self.members), key=lambda pair: -pair[1])

    def _owed(self, member: HuntMember) -> int:
        """Positive: owed to them. Negative: they pay out. One floored division of
        the scaled difference, so the half-gold isn't lost twice."""
        n = len(self.members)
        return (self.balance - n * member.balance) // n

    def transfers(self) -> list[HuntTransfer]:
        """Greedy: each payer covers whoever is still short, in paste order. With one
        leader holding the loot that's one transfer per member, already minimal."""
        if len(self.members) < 2:
            return []
        shortfalls = [[m.name, self._owed(m)] for m in self.members if self._owed(m) > 0]
        settled: list[HuntTransfer] = []
        for payer in (m for m in self.members if self._owed(m) < 0):
            budget = -self._owed(payer)
            remaining = []
            for name, short in shortfalls:
                amount = min(budget, short)
                if amount <= 0:
                    remaining.append([name, short])
                    continue
                settled.append(HuntTransfer(payer.name, name, amount))
                budget -= amount
                if short > amount:
                    remaining.append([name, short - amount])
            shortfalls = remaining
        return settled

    def transfers_by_payer(self) -> list[tuple[str, list[HuntTransfer]]]:
        grouped: dict[str, list[HuntTransfer]] = {}
        for t in self.transfers():
            grouped.setdefault(t.sender, []).append(t)
        seen: list[str] = []
        for m in self.members:
            if m.name in grouped and m.name not in seen:
                seen.append(m.name)
        return [(name, grouped[name]) for name in seen]


def parse(text: str) -> HuntSession:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ParseError("There was nothing in that box to read.")
    head, rest = lines[0], lines[1:]
    if not head.lower().startswith("session data:"):
        raise ParseError("That doesn't look like a party hunt analyser. Copy the whole session out of the "
                         f"party window — it starts with a `Session data:` line, and yours starts with "
                         f"`{_preview(head)}`.")
    header, blocks = _split(rest)
    balance = _number(header.get("balance"))
    if balance is None:
        raise ParseError("I couldn't find the session's `Balance:` line. Copy the whole session rather than part of it.")
    started, ended = _timestamps(head)
    return HuntSession(
        started=started, ended=ended,
        session_label=header.get("session", ""), loot_type=header.get("loot type", ""),
        loot=_number(header.get("loot")) or 0, supplies=_number(header.get("supplies")) or 0,
        balance=balance, members=_members(blocks))


def _split(lines: list[str]) -> tuple[dict[str, str], list[dict]]:
    header: dict[str, str] = {}
    blocks: list[dict] = []
    for line in lines:
        key_value = _key_line(line)
        if key_value and not blocks:
            header[key_value[0]] = key_value[1]
        elif key_value:
            blocks[-1]["values"][key_value[0]] = key_value[1]
        else:
            blocks.append({"name": _LEADER.sub("", line).strip(), "leader": bool(_LEADER.search(line)),
                           "values": {}})
    return header, blocks


def _key_line(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    key, value = line.split(":", 1)
    key = key.strip().lower()
    return (key, value.strip()) if key in HEADER_KEYS or key in MEMBER_KEYS else None


def _members(blocks: list[dict]) -> list[HuntMember]:
    incomplete = [b for b in blocks if not MONEY_KEYS <= set(b["values"])]
    if incomplete and incomplete == [blocks[-1]]:
        raise ParseError(f"That paste stops part-way through **{_preview(blocks[-1]['name'])}** — Discord's box holds "
                         "4,000 characters, and the session is longer than that. Split the party's loot in the "
                         "game client instead.")
    if incomplete:
        raise ParseError(f"**{_preview(incomplete[0]['name'])}** is missing a `Loot:`, `Supplies:` or `Balance:` "
                         "line. Copy the session again without editing it.")
    return [HuntMember(name=b["name"], leader=b["leader"],
                       **{k: _number(b["values"].get(k)) or 0 for k in sorted(MEMBER_KEYS)})
            for b in blocks]


def _timestamps(head: str) -> tuple[datetime | None, datetime | None]:
    match = _SESSION_DATA.match(head)
    if not match:
        return None, None
    return _stamp(match.group(1)), _stamp(match.group(2))


def _stamp(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), _STAMP)
    except ValueError:
        return None


def _number(raw: str | None) -> int | None:
    """`-748,351` -> -748351. The separator depends on the client's locale, so
    only digits and a leading minus count."""
    if raw is None:
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    if not digits:
        return None
    return -int(digits) if raw.strip().startswith("-") else int(digits)


def _preview(line: str) -> str:
    return line if len(line) <= 40 else line[:39].strip() + "…"
