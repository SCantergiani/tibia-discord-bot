"""Hunted/allied list changes for one Discord server at a time.

Lists are held in memory (what deaths and online lists read on every poll) and
written through to the guild's database. A name is looked up once when added,
and that sheet is filed in the shared list cache so the list can be drawn
without asking TibiaData anything.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord

from tibiabot import adminlog
from tibiabot.lists import embeds as list_embeds
from tibiabot.lists import load as tracking_load
from tibiabot.lists import repo
from tibiabot.lists.models import (GRACE_BEFORE_REMOVAL, NO_TAG, BulkOutcome, Finding, GuildLists, ListedGuild,
                                   ListedPlayer, capitalize_words, find_tag, review, review_missing)
from tibiabot.poller import WorldSnapshot
from tibiabot.tibiadata.client import NotFound, TibiaDataError
from tibiabot.tibiadata.models import Character

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

LOOKUP_CONCURRENCY = 4
QUIET_FOR = timedelta(hours=24)
REVIEW_PER_SWEEP = 20

class ListService:
    def __init__(self, bot: TibiaBot):
        self.bot = bot
        self.lists: dict[int, GuildLists] = {}

    # --- state ---------------------------------------------------------------

    def of(self, guild_id: int) -> GuildLists:
        return self.lists.setdefault(guild_id, GuildLists())

    async def load(self, guild_id: int) -> None:
        self.lists[guild_id] = await repo.load_lists(await self.bot.db.guild(guild_id))

    def forget(self, guild_id: int) -> None:
        self.lists.pop(guild_id, None)

    def _tracked_worlds(self, guild_id: int) -> set[str]:
        return set(self.bot.state.guild(guild_id).worlds)

    def usage(self, guild_id: int) -> tracking_load.Load:
        """How much this server's lists cost right now (see lists/load.py)."""
        lists = self.of(guild_id)
        enemies, allies = lists.side_names(True), lists.side_names(False) - lists.side_names(True)
        online = {name.lower() for world in self._tracked_worlds(guild_id) if world in self.bot.online
                  for name in self.bot.online[world].players}
        settings = self.bot.settings
        fast = settings.fresh_tibiadata and settings.fast_poll_seconds > 0
        rate = self.bot.rate
        by_name = set(lists.allied_players) - enemies  # only these allies get fast checks
        return tracking_load.estimate(len(enemies | allies), len(online & enemies), len(online & by_name),
                                      settings.fast_poll_seconds if fast else None,
                                      settings.ally_poll_seconds if fast else None,
                                      (rate.rate if rate else settings.fast_poll_max_per_second) if fast else None,
                                      guild_allies=len(online & (allies - by_name)),
                                      fast_tracked=len(enemies | by_name))

    # --- lookups -------------------------------------------------------------

    async def _lookup(self, name: str) -> Character | None | Exception:
        """The sheet; None when no such character; the error when TibiaData didn't answer."""
        try:
            character = await self.bot.sheets.get(name)
        except NotFound:
            return None
        except TibiaDataError as e:
            return e
        await self._cache(character)
        return character

    async def _cache(self, c: Character) -> None:
        try:
            await repo.cache_sheet(self.bot.db.cache, c.name, c.former_names, c.world, c.former_worlds,
                                   c.guild_name or "", c.level, c.vocation,
                                   c.last_login.isoformat().replace("+00:00", "Z") if c.last_login else "")
        except Exception as e:
            log.warning("Could not cache the sheet for %s: %s", c.name, e)

    # --- bulk changes --------------------------------------------------------

    async def add_many(self, guild: discord.Guild, hunted: bool, kind: str, names: list[str], reason: str,
                       actor_id: str, tag: str = "") -> BulkOutcome:
        lists = self.of(guild.id)
        existing = lists.guilds(hunted) if kind == "guild" else lists.players(hunted)
        already = [n for n in names if n.lower() in existing]
        fresh = [n for n in names if n.lower() not in existing]
        # Re-adding with a tag picked is how an existing entry is retagged.
        if hunted and kind == "player" and tag:
            await self.tag_many(guild, already, tag)
        outcome = BulkOutcome(already=already)
        reason_flag, reason_text = ("true", reason) if reason else ("false", "none")
        gate = asyncio.Semaphore(LOOKUP_CONCURRENCY)

        async def one(name: str) -> BulkOutcome:
            async with gate:
                if kind == "guild":
                    return await self._add_guild(guild, hunted, name, reason_flag, reason_text, actor_id)
                return await self._add_player(guild, hunted, name, reason_flag, reason_text, actor_id, tag)

        for result in await asyncio.gather(*(one(n) for n in fresh)):
            outcome = outcome.merge(result)
        return outcome

    async def _add_player(self, guild: discord.Guild, hunted: bool, name: str, reason_flag: str, reason_text: str,
                          actor_id: str, tag: str) -> BulkOutcome:
        found = await self._lookup(name)
        if found is None:
            return BulkOutcome(not_found=[name])
        if isinstance(found, Exception):
            return BulkOutcome(unavailable=[name])
        # The traded flag is a snapshot: someone listed while already traded was
        # listed on purpose and must never be flagged for it later.
        entry = ListedPlayer(found.name.lower(), reason_flag, reason_text, actor_id,
                             traded_when_added=found.traded, tag=tag if hunted and tag != NO_TAG else "")
        await repo.add_player(await self.bot.db.guild(guild.id), hunted, entry)
        self.of(guild.id).players(hunted)[entry.name] = entry
        return BulkOutcome(added=[found.name])

    async def _add_guild(self, guild: discord.Guild, hunted: bool, name: str, reason_flag: str, reason_text: str,
                         actor_id: str) -> BulkOutcome:
        try:
            tibia_guild = await self.bot.bulk.guild(name)
        except NotFound:
            return BulkOutcome(not_found=[name])
        except TibiaDataError:
            return BulkOutcome(unavailable=[name])
        if not tibia_guild.name:
            return BulkOutcome(not_found=[name])
        entry = ListedGuild(tibia_guild.name.lower(), reason_flag, reason_text, actor_id)
        pool = await self.bot.db.guild(guild.id)
        await repo.add_guild(pool, hunted, entry)
        # The roster is how a member is recognised without fetching their sheet.
        await repo.replace_roster(pool, tibia_guild.name, [m.name for m in tibia_guild.members])
        lists = self.of(guild.id)
        lists.guilds(hunted)[entry.name] = entry
        lists.rosters[entry.name] = {m.name.lower() for m in tibia_guild.members}
        return BulkOutcome(added=[tibia_guild.name])

    async def remove_many(self, guild: discord.Guild, hunted: bool, kind: str, names: list[str]) -> BulkOutcome:
        lists = self.of(guild.id)
        present = lists.guilds(hunted) if kind == "guild" else lists.players(hunted)
        found = [n for n in names if n.lower() in present]
        missing = [n for n in names if n.lower() not in present]
        pool = await self.bot.db.guild(guild.id)
        for name in found:
            present.pop(name.lower(), None)
            if kind == "guild":
                await repo.remove_guild(pool, hunted, name)
            else:
                await repo.remove_player(pool, hunted, name)
        if kind == "guild":
            await repo.remove_activity_by_guilds(pool, found)
            for name in found:
                lists.rosters.pop(name.lower(), None)
        else:
            await repo.remove_activity_by_names(pool, found)
        return BulkOutcome(added=found, not_found=missing)

    async def tag_many(self, guild: discord.Guild, names: list[str], tag: str) -> BulkOutcome:
        stored = "" if tag == NO_TAG else tag
        players = self.of(guild.id).hunted_players
        found = [n for n in names if n.lower() in players]
        pool = await self.bot.db.guild(guild.id)
        for name in found:
            await repo.set_tag(pool, name, stored)
            players[name.lower()] = players[name.lower()].with_(tag=stored)
        return BulkOutcome(added=found, not_found=[n for n in names if n.lower() not in players])

    async def clear(self, guild: discord.Guild, hunted: bool) -> tuple[int, int]:
        lists = self.of(guild.id)
        players, guilds = list(lists.players(hunted)), list(lists.guilds(hunted))
        pool = await self.bot.db.guild(guild.id)
        await repo.clear(pool, hunted)
        await repo.remove_activity_by_guilds(pool, guilds)
        await repo.remove_activity_by_names(pool, players)
        lists.players(hunted).clear()
        lists.guilds(hunted).clear()
        for name in guilds:
            lists.rosters.pop(name, None)
        return len(players), len(guilds)

    async def log_bulk(self, guild: discord.Guild, hunted: bool, adding: bool, actor: str,
                       outcome: BulkOutcome, kind: str) -> None:
        if not outcome.changed_anything:
            return
        link = list_embeds.guild_url if kind == "guild" else list_embeds.char_url
        shown = ", ".join(f"**[{n}]({link(n)})**" for n in outcome.added[:20])
        more = f" and {len(outcome.added) - 20} more" if len(outcome.added) > 20 else ""
        await adminlog.post(
            guild, self.bot.state.guild(guild.id).info,
            f"{adminlog.user(actor)} {'added' if adding else 'removed'} {len(outcome.added)} "
            f"{'to' if adding else 'from'} the {'hunted' if hunted else 'allies'} list:\n{shown}{more}.",
            list_embeds.thumbnail(hunted))

    # --- drawing -------------------------------------------------------------

    async def embeds(self, guild: discord.Guild, hunted: bool) -> list[discord.Embed]:
        lists = self.of(guild.id)
        players = list(lists.players(hunted).values())
        sheets = await repo.cached_sheets(self.bot.db.cache, [p.name for p in players])
        counts = await repo.activity_counts(await self.bot.db.guild(guild.id))
        lines = list_embeds.player_lines(players, sheets, set(lists.allied_guilds), set(lists.hunted_guilds), hunted)
        pages = (list_embeds.guilds_embeds(list(lists.guilds(hunted).values()), counts, hunted)
                 + list_embeds.players_embeds(lines, hunted))
        pages[-1].set_footer(text=self.usage(guild.id).text())
        return pages

    def added_by_name(self, guild: discord.Guild, user_id: str) -> str:
        member = guild.get_member(int(user_id)) if user_id.isdigit() else None
        return adminlog.user(member.name) if member else "**`someone`**"

    # --- keeping lists honest ------------------------------------------------

    async def on_snapshot(self, snapshot: WorldSnapshot) -> None:
        """Refresh the cached sheet of every listed player the poll just fetched,
        and flag anyone it shows was traded, deleted-pending or moved away."""
        by_name = {name.lower(): c for name, c in snapshot.characters.items()}
        cached: set[str] = set()
        for guild_id, _ in self.bot.state.guilds_tracking(snapshot.world):
            lists = self.of(guild_id)
            tracked = self._tracked_worlds(guild_id)
            for hunted in (True, False):
                for entry in list(lists.players(hunted).values()):
                    character = by_name.get(entry.name)
                    if character is None:
                        continue
                    if entry.name not in cached:
                        cached.add(entry.name)
                        await self._cache(character)
                    finding = review(entry, character.traded, character.world, tracked, character.deletion_date)
                    if finding:
                        await self._flag(guild_id, hunted, entry, finding)

    async def refresh_rosters(self) -> None:
        """Re-read every listed guild's member list (once per guild, however many
        servers list it), so a new recruit counts as an ally or enemy at once."""
        wanted: dict[str, list[int]] = {}
        for guild_id, lists in self.lists.items():
            for name in [*lists.hunted_guilds, *lists.allied_guilds]:
                wanted.setdefault(name, []).append(guild_id)
        for name, guild_ids in wanted.items():
            try:
                tibia_guild = await self.bot.bulk.guild(name)
            except TibiaDataError as e:
                log.debug("Roster refresh for %s failed: %s", name, e)
                continue
            members = [m.name for m in tibia_guild.members]
            for guild_id in guild_ids:
                lists = self.lists.get(guild_id)
                if lists is None:
                    continue
                lists.rosters[name] = {m.lower() for m in members}
                try:
                    await repo.replace_roster(await self.bot.db.guild(guild_id), tibia_guild.name, members)
                except Exception:
                    log.exception("Could not store the %s roster for guild %s", name, guild_id)

    async def review_sweep(self) -> None:
        """Every server: look up a few listed players the poll hasn't seen in a day,
        then remove flagged entries whose grace period is over (if still true)."""
        for guild_id in list(self.lists):
            try:
                await self._review_quiet(guild_id)
                await self._prune_flagged(guild_id)
            except Exception:
                log.exception("List review failed for guild %s", guild_id)

    async def _review_quiet(self, guild_id: int) -> None:
        tracked = self._tracked_worlds(guild_id)
        if not tracked:
            return
        lists = self.of(guild_id)
        candidates = [(e, h) for h in (True, False) for e in lists.players(h).values() if not e.flagged_reason]
        sheets = await repo.cached_sheets(self.bot.db.cache, [e.name for e, _ in candidates])
        cutoff = datetime.now(timezone.utc) - QUIET_FOR
        quiet = [(e, h) for e, h in candidates
                 if not (s := sheets.get(e.name)) or not s.updated or s.updated < cutoff][:REVIEW_PER_SWEEP]
        for entry, hunted in quiet:
            found = await self._lookup(entry.name)
            if isinstance(found, Exception):
                continue
            finding = (review_missing(entry) if found is None
                       else review(entry, found.traded, found.world, tracked, found.deletion_date))
            if finding:
                await self._flag(guild_id, hunted, entry, finding)

    async def _prune_flagged(self, guild_id: int) -> None:
        tracked = self._tracked_worlds(guild_id)
        now = datetime.now(timezone.utc)
        lists = self.of(guild_id)
        for hunted in (True, False):
            for entry in list(lists.players(hunted).values()):
                if not entry.flagged_reason:
                    continue
                try:
                    if datetime.fromisoformat(entry.flagged_at) + GRACE_BEFORE_REMOVAL > now:
                        continue
                except ValueError:
                    continue
                found = await self._lookup(entry.name)
                if isinstance(found, Exception):
                    continue  # removal only ever happens on a positive answer
                still_wrong = found is None or review(entry.with_(flagged_reason=""), found.traded, found.world,
                                                      tracked, found.deletion_date) is not None
                if still_wrong:
                    await self._remove_flagged(guild_id, hunted, entry)
                else:
                    await self._unflag(guild_id, hunted, entry)

    async def _flag(self, guild_id: int, hunted: bool, entry: ListedPlayer, finding: Finding) -> None:
        pool = await self.bot.db.guild(guild_id)
        at = await repo.flag_player(pool, hunted, entry.name, finding.reason)
        self.of(guild_id).players(hunted)[entry.name] = entry.with_(flagged_reason=finding.reason, flagged_at=at)
        because = {
            "gone": "no longer exists under that name — deleted, or renamed and not seen since",
            "deletion": f"is **scheduled for deletion** (**{finding.detail}**)",
            "traded": "has been **traded** since being added",
            "world": f"has moved to **{finding.detail}**, which isn't set up here",
        }[finding.reason]
        removal = int((datetime.now(timezone.utc) + GRACE_BEFORE_REMOVAL).timestamp())
        shown = capitalize_words(entry.name)
        await self._automatic(guild_id, hunted, f":robot: {'enemy' if hunted else 'ally'} flagged for removal:",
                              f"**[{shown}]({list_embeds.char_url(shown)})** {because}, so the character has been "
                              f"flagged for removal.\nIt will be removed from the "
                              f"{'hunted' if hunted else 'allies'} list <t:{removal}:R>")

    async def _unflag(self, guild_id: int, hunted: bool, entry: ListedPlayer) -> None:
        await repo.unflag_player(await self.bot.db.guild(guild_id), hunted, entry.name)
        self.of(guild_id).players(hunted)[entry.name] = entry.with_(flagged_reason="", flagged_at="")
        shown = capitalize_words(entry.name)
        await self._automatic(guild_id, hunted, f":robot: {'enemy' if hunted else 'ally'} no longer flagged:",
                              f"**[{shown}]({list_embeds.char_url(shown)})** was flagged for removal, but that no "
                              f"longer applies, so they stay on the {'hunted' if hunted else 'allies'} list.")

    async def _remove_flagged(self, guild_id: int, hunted: bool, entry: ListedPlayer) -> None:
        pool = await self.bot.db.guild(guild_id)
        await repo.remove_player(pool, hunted, entry.name)
        await repo.remove_activity_by_names(pool, [entry.name])
        self.of(guild_id).players(hunted).pop(entry.name, None)
        shown = capitalize_words(entry.name)
        await self._automatic(guild_id, hunted, f":robot: {'enemy' if hunted else 'ally'} removed:",
                              f"**[{shown}]({list_embeds.char_url(shown)})** was flagged for removal and the finding "
                              f"still stands, so they have been removed from the "
                              f"{'hunted' if hunted else 'allies'} list.")

    async def _automatic(self, guild_id: int, hunted: bool, title: str, text: str) -> None:
        guild = self.bot.get_guild(guild_id)
        if guild:
            await adminlog.post(guild, self.bot.state.guild(guild_id).info, text, list_embeds.thumbnail(hunted),
                                title=title, automatic=True)

def tag_label(tag_key: str) -> str:
    tag = find_tag(tag_key)
    return f"{tag.emoji} **{tag.label}**" if tag else "**no tag**"
