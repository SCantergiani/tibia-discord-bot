"""`/hunted` and `/allies`: the list itself, with buttons to change it.

Button ids are stateless (`panel:<hunted|allies>:<action>[:<player>]`) so a panel
keeps working across restarts, and every press and every form submit re-checks
that the person is a moderator: ids are client-supplied.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from tibiabot import adminlog, embeds, emojis
from tibiabot.db import repos
from tibiabot.lists import embeds as list_embeds
from tibiabot.lists.models import MAX_NAMES, NO_TAG, TAGS, find_tag, parse_names
from tibiabot.lists.service import tag_label
from tibiabot.permissions import is_moderator

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

ADD, REMOVE, CONFIG, INFO, CLEAR, CLEAR_CONFIRM, CANCEL, TAG_ONE = (
    "add", "remove", "config", "info", "clear", "clearconfirm", "cancel", "tagone")
FORM_ACTIONS = {ADD, REMOVE, CONFIG, INFO}


def _hunted(panel: str) -> bool:
    return panel == "hunted"


def _refusal() -> discord.Embed:
    return embeds.error("You do not have permission to use this command.")


def _allowed(bot: TibiaBot, interaction: discord.Interaction) -> bool:
    info = bot.state.guild(interaction.guild_id).info
    return interaction.guild is not None and is_moderator(interaction.user, info.moderator_role if info else None)


def panel_view(panel: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action, label, emoji, style in (
            (ADD, "Add", "➕", discord.ButtonStyle.secondary),
            (REMOVE, "Remove", "➖", discord.ButtonStyle.secondary),
            (CONFIG, "Config", "⚙️", discord.ButtonStyle.secondary),
            (INFO, None, "🔍", discord.ButtonStyle.secondary),
            (CLEAR, "Clear All", "🗑️", discord.ButtonStyle.danger)):
        view.add_item(PanelButton(panel, action, label=label, emoji=emoji, style=style))
    return view


def confirm_view(panel: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(PanelButton(panel, CLEAR_CONFIRM, label="Yes, clear it", style=discord.ButtonStyle.danger))
    view.add_item(PanelButton(panel, CANCEL, label="Cancel", style=discord.ButtonStyle.secondary))
    return view


def lookup_view(panel: str, name: str, current_tag: str) -> discord.ui.View:
    tag = find_tag(current_tag)
    view = discord.ui.View(timeout=None)
    view.add_item(PanelButton(panel, TAG_ONE, subject=name, label=f"Tag: {tag.label}" if tag else "Tag",
                              emoji=tag.emoji if tag else "🏷️", style=discord.ButtonStyle.secondary))
    return view


class PanelButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"panel:(?P<panel>hunted|allies):(?P<action>[a-z]+)(?::(?P<subject>.+))?"):
    def __init__(self, panel: str, action: str, subject: str | None = None, *, label: str | None = None,
                 emoji: str | None = None, style: discord.ButtonStyle = discord.ButtonStyle.secondary):
        custom_id = f"panel:{panel}:{action}" + (f":{subject}" if subject else "")
        super().__init__(discord.ui.Button(custom_id=custom_id, label=label, emoji=emoji, style=style))
        self.panel, self.action, self.subject = panel, action, subject

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match):
        return cls(match["panel"], match["action"], match["subject"])

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        if not _allowed(bot, interaction):
            await interaction.response.send_message(embed=_refusal(), ephemeral=True)
            return
        hunted = _hunted(self.panel)
        lists = bot.lists.of(interaction.guild_id)
        if self.action in FORM_ACTIONS:
            worlds = sorted(bot.state.guild(interaction.guild_id).worlds.values(), key=lambda w: w.name)
            await interaction.response.send_modal(ListForm(self.panel, self.action, worlds))
        elif self.action == TAG_ONE and hunted and self.subject:
            entry = lists.hunted_players.get(self.subject.lower())
            await interaction.response.send_modal(TagForm(self.subject, entry.tag if entry else ""))
        elif self.action == CLEAR:
            players, guilds = len(lists.players(hunted)), len(lists.guilds(hunted))
            if players == 0 and guilds == 0:
                await interaction.response.edit_message(
                    embeds=[embeds.error(f"The {list_embeds.noun(hunted)} is already empty.")], view=None)
            else:
                await interaction.response.edit_message(embeds=[list_embeds.clear_confirm(hunted, players, guilds)],
                                                        view=confirm_view(self.panel))
        elif self.action == CLEAR_CONFIRM:
            players, guilds = await bot.lists.clear(interaction.guild, hunted)
            await interaction.response.edit_message(embeds=[embeds.ok(
                f"The {'hunted' if hunted else 'allies'} list has been cleared — **{players}** "
                f"{'player' if players == 1 else 'players'} and **{guilds}** {'guild' if guilds == 1 else 'guilds'} "
                "removed.")], view=None)
            await adminlog.post(interaction.guild, bot.state.guild(interaction.guild_id).info,
                                f"{adminlog.user(interaction.user.name)} cleared the "
                                f"{'hunted' if hunted else 'allies'} list.", list_embeds.thumbnail(hunted))
        elif self.action == CANCEL:
            pages = list_embeds.batches(await bot.lists.embeds(interaction.guild, hunted))
            await interaction.response.edit_message(embeds=pages[-1], view=panel_view(self.panel))
        else:
            await interaction.response.send_message(embed=embeds.error("That button is out of date."), ephemeral=True)


# --- forms ------------------------------------------------------------------

def _select(custom_id: str, options: list[tuple[str, str]], current: str | None = None, required: bool = False,
            placeholder: str = "Leave unchanged") -> discord.ui.Select:
    return discord.ui.Select(custom_id=custom_id, placeholder=placeholder, required=required,
                             options=[discord.SelectOption(label=label, value=value, default=value == current)
                                      for label, value in options])


def _tag_select(required: bool, current: str | None = None) -> discord.ui.Select:
    options = [discord.SelectOption(label=t.label, value=t.key, emoji=t.emoji, default=t.key == current)
               for t in TAGS]
    options.append(discord.SelectOption(label="No tag", value=NO_TAG, description="Remove any tag this player has"))
    return discord.ui.Select(custom_id="tag", options=options, required=required,
                             placeholder="Pick a tag" if required else "Leave the tag as it is")


def _picked(select: discord.ui.Select | None) -> str | None:
    return select.values[0] if select is not None and select.values else None


class ListForm(discord.ui.Modal):
    def __init__(self, panel: str, action: str, worlds: list[repos.WorldConfig]):
        hunted = _hunted(panel)
        titles = {ADD: f"Add to the {list_embeds.noun(hunted)}", REMOVE: f"Remove from the {list_embeds.noun(hunted)}",
                  INFO: "Look someone up", CONFIG: f"{list_embeds.noun(hunted).capitalize()} config"}
        super().__init__(title=titles[action], custom_id=f"panelform:{panel}:{action}", timeout=None)
        self.panel, self.action, self.hunted = panel, action, hunted
        self.worlds = worlds
        self.kind = self.names = self.reason = self.tag = self.name = None
        self.world = self.levels = self.deaths = self.detect = None

        if action in (ADD, REMOVE):
            verb = "Add" if action == ADD else "Remove"
            self.kind = _select("kind", [("Players", "player"), ("Guilds", "guild")], "player")
            self.add_item(discord.ui.Label(text=f"{verb} players or guilds?",
                                           description="Guilds pull in their whole member list.", component=self.kind))
            self.names = discord.ui.TextInput(style=discord.TextStyle.paragraph, max_length=4000, required=True,
                                              placeholder="One per line — paste a whole list if you have one")
            self.add_item(discord.ui.Label(text="Names", description=f"Up to {MAX_NAMES} at a time.",
                                           component=self.names))
        if action == ADD:
            self.reason = discord.ui.TextInput(style=discord.TextStyle.short, max_length=200, required=False,
                                               placeholder="Why are these being added?")
            self.add_item(discord.ui.Label(text="Reason", description="Optional, and applies to every name here.",
                                           component=self.reason))
            if hunted:
                self.tag = _tag_select(required=False)
                self.add_item(discord.ui.Label(text="Tag", description="Optional, and applies to every player here.",
                                               component=self.tag))
        if action == INFO:
            self.name = discord.ui.TextInput(style=discord.TextStyle.short, max_length=64, required=True,
                                             placeholder="Character or guild name")
            self.add_item(discord.ui.Label(text="Name", description="A player or guild already on the list.",
                                           component=self.name))
        if action == CONFIG:
            only = worlds[0] if len(worlds) == 1 else None
            if len(worlds) > 1:
                self.world = _select("world", [(w.name, w.name) for w in worlds], required=True,
                                     placeholder="Pick a world")
                self.add_item(discord.ui.Label(text="Which world?", description="The world this setting applies to.",
                                               component=self.world))
            side = "enemy" if hunted else "ally"
            levels_col, deaths_col = (("show_enemies_levels", "show_enemies_deaths") if hunted
                                      else ("show_allies_levels", "show_allies_deaths"))
            show_hide = [("Show", "show"), ("Hide", "hide")]
            current = (lambda col: ("show" if getattr(only, col) == "true" else "hide") if only else None)
            self.levels = _select("levels", show_hide, current(levels_col))
            self.deaths = _select("deaths", show_hide, current(deaths_col))
            self.add_item(discord.ui.Label(text=f"{side.capitalize()} levels",
                                           description=f"Level-ups by {side} players.", component=self.levels))
            self.add_item(discord.ui.Label(text=f"{side.capitalize()} deaths",
                                           description=f"Deaths of {side} players.", component=self.deaths))
            if hunted:
                self.detect = _select("activity", [("On", "on"), ("Off", "off")],
                                      (only.detect_hunteds if only else None))
                self.add_item(discord.ui.Label(text="Auto-detect enemies",
                                               description="Add players who kill an ally to the hunted list.",
                                               component=self.detect))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        if not _allowed(bot, interaction):
            await interaction.response.send_message(embed=_refusal(), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.action in (ADD, REMOVE):
            await self._bulk(bot, interaction)
        elif self.action == INFO:
            await self._info(bot, interaction)
        elif self.action == CONFIG:
            await self._config(bot, interaction)

    async def _bulk(self, bot: TibiaBot, interaction: discord.Interaction) -> None:
        kind = _picked(self.kind) or "player"
        parsed = parse_names(self.names.value)
        names, overflow = parsed[:MAX_NAMES], parsed[MAX_NAMES:]
        if not names:
            await interaction.followup.send(embed=embeds.error("No names in that - one per line."), ephemeral=True)
            return
        adding = self.action == ADD
        tag = (_picked(self.tag) or "") if self.hunted and kind == "player" else ""
        if adding:
            outcome = await bot.lists.add_many(interaction.guild, self.hunted, kind, names,
                                               (self.reason.value or "").strip(), str(interaction.user.id), tag)
        else:
            outcome = await bot.lists.remove_many(interaction.guild, self.hunted, kind, names)
        outcome.skipped += overflow
        await bot.lists.log_bulk(interaction.guild, self.hunted, adding, interaction.user.name, outcome, kind)
        embed = list_embeds.bulk(self.hunted, kind, adding, outcome, find_tag(tag) if adding else None)
        load = bot.lists.usage(interaction.guild_id)
        if adding and load.tracked >= bot.settings.tracked_warn_at:
            embed.add_field(name=":warning: That's a lot to track", inline=False, value=(
                f"{load.text()}.\nOnly allies and enemies **online** cost anything: each gets a fast check, "
                f"up to `FAST_POLL_MAX_PER_SECOND` requests a second. The more are online at once, the longer "
                f"each waits for its turn and the more traffic the server sends."))
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _info(self, bot: TibiaBot, interaction: discord.Interaction) -> None:
        name = self.name.value.strip().lower()
        lists = bot.lists.of(interaction.guild_id)
        player = lists.players(self.hunted).get(name)
        guild_entry = lists.guilds(self.hunted).get(name)
        if player:
            embed = list_embeds.player_info(player, self.hunted, bot.lists.added_by_name(interaction.guild,
                                                                                        player.added_by))
            if self.hunted:
                await interaction.followup.send(embed=embed, view=lookup_view(self.panel, name, player.tag),
                                                ephemeral=True)
                return
        elif guild_entry:
            embed = list_embeds.guild_info(guild_entry, self.hunted, bot.lists.added_by_name(interaction.guild,
                                                                                             guild_entry.added_by))
        else:
            embed = embeds.response(f":gear: **{name}** is not on the {list_embeds.noun(self.hunted)}.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _config(self, bot: TibiaBot, interaction: discord.Interaction) -> None:
        if len(self.worlds) == 1:
            world_name = self.worlds[0].name
        else:
            world_name = _picked(self.world)
        state = bot.state.guild(interaction.guild_id)
        world = state.worlds.get(world_name or "")
        if world is None:
            await interaction.followup.send(embed=embeds.error("Pick a world first."), ephemeral=True)
            return
        side = "enemies" if self.hunted else "allies"
        changes: dict[str, str] = {}
        for select, column in ((self.levels, f"show_{side}_levels"), (self.deaths, f"show_{side}_deaths")):
            if (value := _picked(select)) is not None:
                changes[column] = "true" if value == "show" else "false"
        if (detect := _picked(self.detect)) is not None:
            changes["detect_hunteds"] = detect
        changes = {col: v for col, v in changes.items() if getattr(world, col) != v}
        if not changes:
            await interaction.followup.send(embed=embeds.error("Nothing was changed."), ephemeral=True)
            return
        pool = await bot.db.guild(interaction.guild_id)
        for column, value in changes.items():
            await repos.update_world_setting(pool, world.name, column, value)
        bot.state.set_world(interaction.guild_id, dataclasses.replace(world, **changes))
        described = ", ".join(f"**{_describe(c)}** → **{_value(v)}**" for c, v in changes.items())
        await adminlog.post(interaction.guild, state.info,
                            f"{adminlog.user(interaction.user.name)} changed {described} for **{world.name}**.",
                            f"{embeds.WIKI_FILE}Armillary_Sphere_(TibiaMaps).gif")
        await interaction.followup.send(embed=embeds.response(f":gear: {described} for **{world.name}**."),
                                        ephemeral=True)


def _describe(column: str) -> str:
    return {"show_enemies_levels": "Enemy levels", "show_enemies_deaths": "Enemy deaths",
            "show_allies_levels": "Ally levels", "show_allies_deaths": "Ally deaths",
            "detect_hunteds": "Auto-detect enemies"}.get(column, column)


def _value(value: str) -> str:
    return {"true": "show", "false": "hide"}.get(value, value)


class TagForm(discord.ui.Modal):
    def __init__(self, name: str, current: str):
        super().__init__(title=f"Tag {name}"[:45], custom_id=f"panelform:hunted:tagone:{name}", timeout=None)
        self.player = name
        self.tag = _tag_select(required=True, current=find_tag(current).key if find_tag(current) else None)
        self.add_item(discord.ui.Label(text="Tag", description=f"What {name} is worth knowing for."[:100],
                                       component=self.tag))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        if not _allowed(bot, interaction):
            await interaction.response.send_message(embed=_refusal(), ephemeral=True)
            return
        tag = _picked(self.tag) or NO_TAG
        outcome = await bot.lists.tag_many(interaction.guild, [self.player], tag)
        if not outcome.added:
            await interaction.response.send_message(
                embed=embeds.error(f"**{self.player}** isn't on the hunted list any more."), ephemeral=True)
        else:
            await interaction.response.send_message(
                embed=embeds.ok(f"**{self.player}** is now {tag_label(tag)}."), ephemeral=True)


# --- commands ---------------------------------------------------------------

class ListsCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot

    async def _panel(self, interaction: discord.Interaction, panel: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not _allowed(self.bot, interaction):
            await interaction.followup.send(embed=_refusal(), ephemeral=True)
            return
        if not self.bot.state.guild(interaction.guild_id).worlds:
            await interaction.followup.send(embed=embeds.error("No worlds are set up here yet — run `/setup` first."),
                                            ephemeral=True)
            return
        pages = list_embeds.batches(await self.bot.lists.embeds(interaction.guild, _hunted(panel)))
        for page in pages[:-1]:
            await interaction.followup.send(embeds=page, ephemeral=True)
        await interaction.followup.send(embeds=pages[-1], view=panel_view(panel), ephemeral=True)

    @app_commands.command(name="hunted", description="Manage the hunted list (enemy players and guilds)")
    @app_commands.guild_only()
    async def hunted(self, interaction: discord.Interaction) -> None:
        await self._panel(interaction, "hunted")

    @app_commands.command(name="allies", description="Manage the allies list (allied players and guilds)")
    @app_commands.guild_only()
    async def allies(self, interaction: discord.Interaction) -> None:
        await self._panel(interaction, "allies")


async def setup(bot: TibiaBot) -> None:
    bot.add_dynamic_items(PanelButton)
    await bot.add_cog(ListsCog(bot))
