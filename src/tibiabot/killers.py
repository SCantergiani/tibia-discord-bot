"""Reading a death's killer list: summons, articles, who to exiva, and joining it
all into one sentence that fits an embed. Ported from domain/Killers.scala."""

from __future__ import annotations

SUBSTANCE_SOURCES = {"death", "earth", "energy", "fire", "ice", "holy", "a trap", "agony", "life drain", "drowning",
                     "invalid"}
EXIVA_TARGETS = 5


def article(name: str) -> str:
    return "an" if name[:1].lower() in "aeiou" and name else "a"


def source_article(name: str) -> str:
    """'a dragon ', but no article for a damage type ('fire', 'drowning')."""
    return "" if name in SUBSTANCE_SOURCES else f"{article(name)} "


def parse_summon(name: str) -> tuple[str, str] | None:
    """'fire elemental of Bubble' -> ('fire elemental', 'Bubble'). A player named
    'Knight of Flame' starts uppercase, so it is not a summon."""
    parts = name.split(" of ", 1)
    if len(parts) > 1 and not any(ch.isupper() for ch in parts[0]):
        return parts[0], parts[1]
    return None


def summon_behind(name: str, summon: str) -> tuple[str, str] | None:
    """(creature, summoner) when a player's summon did the damage."""
    if summon and summon.strip():
        return summon.strip(), name
    return parse_summon(name)


def level_lookup_names(victim: str, killers: list[tuple[str, bool]]) -> list[str]:
    """The player names whose level the death post shows: summoners, not summons."""
    names = []
    for name, is_player in killers:
        if is_player and name != victim:
            summon = parse_summon(name)
            names.append(summon[1] if summon else name)
    return names


def join_natural(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def join_within(parts: list[str], limit: int) -> str:
    """Natural join, or as many as fit followed by 'and N more'."""
    full = join_natural(parts)
    if not parts or len(full) <= limit:
        return full
    total = len(parts)
    widths = [0]
    for p in parts:
        widths.append(widths[-1] + len(p))
    for kept in range(total - 1, 0, -1):
        if widths[kept] + 2 * (kept - 1) + len(f" and {total - kept} more") <= limit:
            return ", ".join(parts[:kept]) + f" and {total - kept} more"
    return "1 killer" if total == 1 else f"{total} killers"


def exiva_targets(killers: list[tuple[str, int | None]], limit: int = EXIVA_TARGETS) -> list[str]:
    """Distinct killers, highest level first (ties keep killer order), at most `limit`."""
    best: dict[str, tuple[int | None, int]] = {}
    for order, (name, level) in enumerate(killers):
        if name not in best:
            best[name] = (level, order)
        else:
            old_level, first = best[name]
            levels = [lv for lv in (old_level, level) if lv is not None]
            best[name] = (max(levels) if levels else None, first)
    ranked = sorted(best.items(), key=lambda kv: (-(kv[1][0] or 0), kv[1][1]))
    return [name for name, _ in ranked[:limit]]
