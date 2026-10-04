"""The reply to a pasted analyser: what the party made, who did what, and the
exact commands that square everyone up, one copyable code block each."""

from __future__ import annotations

import io

import discord

from tibiabot.lootsplit import HuntMember, HuntSession, HuntTransfer

SPLIT_COLOR = 3066993
PASTE_FILE_NAME = "session.txt"
MAX_FIELDS = 25
FIELD_VALUE_MAX = 1024
EMBED_MAX = 6000
_BULLET = "‣"
_MARKER_ROOM = 24
_LEFT_OUT_ROOM = 10 + FIELD_VALUE_MAX


def session(hunt: HuntSession, gold_emoji: str) -> discord.Embed:
    embed = discord.Embed(color=SPLIT_COLOR, title=_title(hunt), description="\n".join(_headline(hunt, gold_emoji)))
    _share_field(embed, "Damage", hunt.damage_shares())
    _share_field(embed, "Healing", hunt.healing_shares())
    _transfer_fields(embed, hunt)
    footer = _footer(hunt)
    if footer:
        embed.set_footer(text=footer)
    return embed


def paste(analyser: str) -> discord.File:
    """The analyser text, verbatim, attached beside the split: the modal it came
    in is gone once submitted, and the embed is a reading that drops detail."""
    return discord.File(io.BytesIO(analyser.encode("utf-8")), filename=PASTE_FILE_NAME)


def _title(hunt: HuntSession) -> str:
    n = len(hunt.members)
    if n == 0:
        return "Hunt Session"
    return f"Party Hunt Session – {n} member{'s' if n != 1 else ''}"


def _headline(hunt: HuntSession, gold_emoji: str) -> list[str]:
    lines = [f"Balance: {_gold(hunt.balance, gold_emoji)}"]
    if len(hunt.members) >= 2:
        lines.append(f"Individual balance: {_gold(hunt.individual_balance, gold_emoji)}")
    if hunt.loot_per_hour is not None:
        lines.append(f"Loot per hour: {_gold(hunt.loot_per_hour, gold_emoji)}")
    return lines


def _share_field(embed: discord.Embed, name: str, shares: list[tuple[HuntMember, float]]) -> None:
    if shares:
        embed.add_field(name=name, value=_fit([f"{_BULLET} {m.name} ({share:.2f}%)" for m, share in shares]),
                        inline=True)


def _transfer_fields(embed: discord.Embed, hunt: HuntSession) -> None:
    by_payer = hunt.transfers_by_payer()
    if not by_payer:
        if len(hunt.members) >= 2:
            embed.add_field(name="Transfers", value="Nobody owes anybody — the party is already square.", inline=False)
        return
    # Over 25 fields or 6,000 characters Discord rejects the whole reply, so both
    # are checked as fields go on, keeping a slot for the "left out" notice.
    field_cap = MAX_FIELDS if len(by_payer) <= MAX_FIELDS - len(embed.fields) else MAX_FIELDS - 1
    skipped: list[str] = []
    for payer, transfers in by_payer:
        name = f"Transfers for {payer}"
        value = _fit([_block(t) for t in transfers])
        if len(embed.fields) < field_cap and len(embed) + len(name) + len(value) + _LEFT_OUT_ROOM <= EMBED_MAX:
            embed.add_field(name=name, value=value, inline=False)
        else:
            skipped.append(payer)
    if skipped and len(embed.fields) < MAX_FIELDS:
        embed.add_field(name="Transfers", value=_fit([f"Too many to show. Still to send: {', '.join(skipped)}."]),
                        inline=False)


def _block(transfer: HuntTransfer) -> str:
    return f"```\n{transfer.command}\n```"


def _footer(hunt: HuntSession) -> str | None:
    parts = []
    if hunt.session_label:
        parts.append(f"{hunt.session_label} hunt")
    if hunt.started:
        parts.append(f"on {hunt.started.strftime('%Y-%m-%dT%H:%M')}")
    return " ".join(parts) or None


def _gold(amount: int, gold_emoji: str) -> str:
    return f"**{amount:,}** {gold_emoji}".rstrip()


def _fit(lines: list[str]) -> str:
    """Whole lines only: a cut transfer command would look complete and not be."""
    whole = "\n".join(lines)
    if len(whole) <= FIELD_VALUE_MAX:
        return whole
    kept, used = [], 0
    for line in lines:
        if used + len(line) + 1 <= FIELD_VALUE_MAX - _MARKER_ROOM:
            kept.append(line)
            used += len(line) + 1
    return "\n".join([*kept, f"*…and {len(lines) - len(kept)} more*"])
