"""How the hunted/allies lists and the replies to changing them are drawn."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote_plus

import discord

from tibiabot import embeds, emojis
from tibiabot.lists.models import (GRACE_BEFORE_REMOVAL, BulkOutcome, ListedGuild, ListedPlayer, Tag,
                                   capitalize_words, find_tag, tag_mark)
from tibiabot.lists.repo import CachedSheet

COLOR = embeds.BRAND_COLOR
EMBED_DESCRIPTION_MAX = 4096
MESSAGE_EMBEDS_MAX = 10
MESSAGE_CHARS_MAX = 6000
SHOWN_PER_GROUP = 15
VOCATION_ORDER = ["druid", "knight", "paladin", "sorcerer", "monk", "none"]
SORTS_LAST = {"Not checked yet"}
VOCATION_EMOJI = {"knight": ":shield:", "druid": ":snowflake:", "sorcerer": ":fire:", "paladin": ":bow_and_arrow:",
                  "monk": ":fist::skin-tone-3:", "none": ":hatching_chick:"}


def thumbnail(hunted: bool) -> str:
    return f"{embeds.WIKI_FILE}{'Stone_Coffin' if hunted else 'Angel_Statue'}.gif"


def noun(hunted: bool) -> str:
    return "hunted list" if hunted else "allies list"


def char_url(name: str) -> str:
    return f"https://www.tibia.com/community/?name={quote_plus(name)}"


def guild_url(name: str) -> str:
    return f"https://www.tibia.com/community/?subtopic=guilds&page=view&GuildName={quote_plus(name)}"


def vocation_key(vocation: str) -> str:
    return (vocation.lower().split(" ")[-1] if vocation else "") or "none"


def guild_icon(guild_name: str, allied_guild: bool, hunted_guild: bool, hunted_list: bool) -> str:
    """Which icons a list row's guild earns, matching GuildIcons.classifyList."""
    e = emojis.get
    if not hunted_list:
        if allied_guild:
            return e("allyguild")
        if hunted_guild:
            return e("enemyguild") + e("ally")
        return e("ally") if not guild_name else e("neutralguild") + e("ally")
    if hunted_guild:
        return e("enemyguild")
    if allied_guild:
        return e("allyguild") + e("enemy")
    return e("enemy") if not guild_name else e("neutralguild") + e("enemy")


def recent_login(last_login: str, now: datetime) -> str:
    try:
        when = datetime.fromisoformat(last_login.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return ""
    if abs((now - when).total_seconds()) > 24 * 3600:
        return ""
    return f"{emojis.get('daily')}<t:{int(when.timestamp())}:R>"


def flag_mark(entry: ListedPlayer) -> str:
    if not entry.flagged_reason:
        return ""
    try:
        at = datetime.fromisoformat(entry.flagged_at)
    except ValueError:
        return " :triangular_flag_on_post:"
    return f" :triangular_flag_on_post: _removed <t:{int((at + GRACE_BEFORE_REMOVAL).timestamp())}:R>_"


def player_lines(listed: list[ListedPlayer], sheets: dict[str, CachedSheet], guild_lists_allied: set[str],
                 guild_lists_hunted: set[str], hunted_list: bool, now: datetime | None = None) -> list[str]:
    """`## World` headings, then players by vocation (display order) and level, highest first."""
    now = now or datetime.now(timezone.utc)
    by_world: dict[str, list[tuple[int, int, str]]] = {}
    for entry in listed:
        sheet = sheets.get(entry.name)
        marks = f"{tag_mark(entry.tag)}{flag_mark(entry)}"
        if sheet and sheet.vocation:
            voc = vocation_key(sheet.vocation)
            level = int(sheet.level) if sheet.level.isdigit() else 0
            icon = guild_icon(sheet.guild_name, sheet.guild_name.lower() in guild_lists_allied,
                              sheet.guild_name.lower() in guild_lists_hunted, hunted_list)
            login = recent_login(sheet.last_login, now)
            line = (f"{VOCATION_EMOJI.get(voc, '')} **{sheet.level}** - **[{sheet.name}]({char_url(sheet.name)})** "
                    f"{icon} {login}{marks}")
            world = sheet.world
        else:
            voc, level, world = "none", 0, "Not checked yet"
            shown = capitalize_words(entry.name)
            line = f":grey_question: **?** - **[{shown}]({char_url(shown)})**{marks}"
        order = VOCATION_ORDER.index(voc) if voc in VOCATION_ORDER else len(VOCATION_ORDER) - 1
        by_world.setdefault(world, []).append((order, -level, line))
    worlds = sorted(by_world, key=lambda w: (w in SORTS_LAST, w))
    lines: list[str] = []
    for world in worlds:
        lines.append(f"## {world}")
        lines.extend(line for _, _, line in sorted(by_world[world], key=lambda t: (t[0], t[1])))
    return lines


def pack(lines: list[str], limit: int = EMBED_DESCRIPTION_MAX) -> list[str]:
    """Whole lines per page. A `## ` heading never ends a page: it moves to the
    next one with the players it introduces."""
    pages: list[list[str]] = [[]]
    size = 0
    for i, line in enumerate(lines):
        is_heading = line.startswith("## ")
        needed = len(line) + 1 + (len(lines[i + 1]) + 1 if is_heading and i + 1 < len(lines) else 0)
        if pages[-1] and size + needed > limit:
            pages.append([])
            size = 0
        pages[-1].append(line)
        size += len(line) + 1
    return ["\n".join(p) for p in pages if p]


def players_embeds(lines: list[str], hunted: bool) -> list[discord.Embed]:
    if not lines:
        embed = discord.Embed(title="Players", description="*Nobody on the list yet.*", color=COLOR)
        embed.set_thumbnail(url=thumbnail(hunted))
        return [embed]
    out = []
    for i, page in enumerate(pack(lines)):
        embed = discord.Embed(description=page, color=COLOR)
        if i == 0:
            embed.title = "Players"
            embed.set_thumbnail(url=thumbnail(hunted))
        out.append(embed)
    return out


def guilds_embeds(listed: list[ListedGuild], member_counts: dict[str, int], hunted: bool) -> list[discord.Embed]:
    if not listed:
        embed = discord.Embed(title="Guilds", description="*No guilds on the list yet.*", color=COLOR)
        embed.set_thumbnail(url=thumbnail(hunted))
        return [embed]
    lines = []
    for g in sorted(listed, key=lambda g: g.name):
        shown = capitalize_words(g.name)
        members = f" — **{member_counts[g.name]}** members" if g.name in member_counts else ""
        note = " :pencil:" if g.reason == "true" else ""
        lines.append(f"**[{shown}]({guild_url(shown)})**{members}{note}")
    out = []
    for i, page in enumerate(pack(lines)):
        embed = discord.Embed(description=page, color=COLOR)
        if i == 0:
            embed.title = "Guilds"
            embed.set_thumbnail(url=thumbnail(hunted))
        out.append(embed)
    return out


def batches(items: list[discord.Embed]) -> list[list[discord.Embed]]:
    """Group embeds into messages: at most 10 each and 6,000 characters across them."""
    out: list[list[discord.Embed]] = []
    current: list[discord.Embed] = []
    length = 0
    for embed in items:
        size = len(embed)
        if current and (length + size > MESSAGE_CHARS_MAX or len(current) >= MESSAGE_EMBEDS_MAX):
            out.append(current)
            current, length = [], 0
        current.append(embed)
        length += size
    if current:
        out.append(current)
    return out


def bulk(hunted: bool, kind: str, adding: bool, outcome: BulkOutcome, tag: Tag | None = None) -> discord.Embed:
    what_noun = "guild" if kind == "guild" else "player"
    what = f"{'added to' if adding else 'removed from'} the {noun(hunted)}"
    count = len(outcome.added)
    headline = (f"Nothing was {what}." if count == 0
                else f"**1** {what_noun} {what}." if count == 1
                else f"**{count}** {what_noun}s {what}.")
    embed = discord.Embed(description=headline, color=COLOR)
    if tag:
        embed.description += f"\nTagged {tag.emoji} **{tag.label}**."
    yes = emojis.get("yes")
    groups = [
        (f"{yes} {'Added' if adding else 'Removed'}", outcome.added),
        (":arrow_right_hook: Already on the list", outcome.already),
        (":grey_question: No such character" if adding else ":grey_question: Not on the list", outcome.not_found),
        (":warning: Couldn't check", outcome.unavailable),
        (":no_entry: Over the limit", outcome.skipped),
    ]
    for title, names in groups:
        if names:
            shown = ", ".join(f"`{n}`" for n in names[:SHOWN_PER_GROUP])
            more = f" _and {len(names) - SHOWN_PER_GROUP} more_" if len(names) > SHOWN_PER_GROUP else ""
            value = shown + more
            embed.add_field(name=f"{title} ({len(names)})",
                            value=value if len(value) <= 1024 else value[:1022].strip() + "…", inline=False)
    if outcome.unavailable:
        embed.description += (f"\n\n{emojis.get('no')} Tibia's API didn't answer for {len(outcome.unavailable)} of "
                              "these, so they were left alone. Paste them again to retry.")
    if outcome.skipped:
        processed = len(outcome.added) + len(outcome.already) + len(outcome.not_found) + len(outcome.unavailable)
        embed.description += f"\n\nOnly the first {processed} were processed - paste the rest separately."
    return embed


def player_info(entry: ListedPlayer, hunted: bool, added_by: str) -> discord.Embed:
    shown = capitalize_words(entry.name)
    tag = find_tag(entry.tag)
    lines = [f"**Player:** [{shown}]({char_url(shown)})", f"**added by:** {added_by}",
             f"**reason:** {entry.reason_text}"]
    if tag:
        lines.append(f"**tag:** {tag.emoji} {tag.label}")
    embed = discord.Embed(title=f":gear: {'hunted' if hunted else 'allied'} player details:",
                          description="\n".join(lines), color=COLOR)
    embed.set_thumbnail(url=f"{embeds.WIKI_FILE}Tibiapedia.gif")
    return embed


def guild_info(entry: ListedGuild, hunted: bool, added_by: str) -> discord.Embed:
    shown = capitalize_words(entry.name)
    embed = discord.Embed(title=f":gear: {'hunted' if hunted else 'allied'} guild details:",
                          description=f"**Guild:** [{shown}]({guild_url(shown)})\n**added by:** {added_by}\n"
                                      f"**reason:** {entry.reason_text}", color=COLOR)
    embed.set_thumbnail(url=f"{embeds.WIKI_FILE}Tibiapedia.gif")
    return embed


def clear_confirm(hunted: bool, players: int, guilds: int) -> discord.Embed:
    return embeds.response(
        f"{emojis.get('no')} This clears **{players}** {'player' if players == 1 else 'players'} and "
        f"**{guilds}** {'guild' if guilds == 1 else 'guilds'} from the {noun(hunted)}.\n\nThis cannot be undone.")
