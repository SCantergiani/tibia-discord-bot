"""`/settings` (Manage Server): per-world death/level filters and the command log
channel. Also the role buttons members press to opt in to death pings."""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from tibiabot import adminlog, embeds, emojis, visibility
from tibiabot.db import repos
from tibiabot.db.repos import WorldConfig
from tibiabot.online import MASSLOG_EVERYONE, MASSLOG_MEMBERS, masslog_mode
from tibiabot.permissions import has_manage_server

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

FULLBLESS, EXIVA, CHANNEL_FILTER, NEUTRAL, COMMAND_LOG = "fullbless", "exiva", "chanfilter", "neutral", "cmdlog"
ONLINE_FILTER = "onlinefilter"
MASSLOG = "masslog"
MEMBER_ROLE = "memberrole"
MASSLOG_MODES = [("Ping the Masslog role", "role"), ("Ping the member role", "members"),
                 ("Ping everyone", "everyone"), ("Off", "off")]
SHOW_HIDE = [("Show", "show"), ("Hide", "hide")]
SETTINGS_THUMBNAIL = f"{embeds.WIKI_FILE}Armillary_Sphere_(TibiaMaps).gif"


def _refusal() -> discord.Embed:
    return embeds.error("You need **Manage Server** to change these settings.")


def settings_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for action, label, emoji in ((FULLBLESS, "Fullbless", emojis.get("inq") or "🕯️"),
                                 (EXIVA, "Exiva Lists", emojis.get("exiva") or "🧭"),
                                 (CHANNEL_FILTER, "Channel Filters", "📊"),
                                 (ONLINE_FILTER, "Online Filters", "📋"),
                                 (MASSLOG, "Mass Log", emojis.get("masslog") or "⚡"),
                                 (NEUTRAL, "Neutrals", "⚪"),
                                 (COMMAND_LOG, "Command Log", "🖥️"),
                                 (MEMBER_ROLE, "Member Role", "👥")):
        view.add_item(SettingsButton(action, label=label, emoji=emoji))
    return view


class SettingsButton(discord.ui.DynamicItem[discord.ui.Button], template=r"settings:(?P<action>[a-z]+)"):
    def __init__(self, action: str, *, label: str | None = None, emoji: str | None = None):
        super().__init__(discord.ui.Button(custom_id=f"settings:{action}", label=label, emoji=emoji,
                                           style=discord.ButtonStyle.secondary))
        self.action = action

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match):
        return cls(match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        if not has_manage_server(interaction.user):
            await interaction.response.send_message(embed=_refusal(), ephemeral=True)
            return
        state = bot.state.guild(interaction.guild_id)
        worlds = sorted(state.worlds.values(), key=lambda w: w.name)
        if not worlds:
            await interaction.response.send_message(embed=embeds.error("Run `/init` first."), ephemeral=True)
            return
        await interaction.response.send_modal(SettingsForm(self.action, worlds))


def _number(current: int | None, placeholder: str) -> discord.ui.TextInput:
    return discord.ui.TextInput(style=discord.TextStyle.short, required=False, max_length=4, placeholder=placeholder,
                                default=str(current) if current is not None else None)


def _choice(custom_id: str, current: str | None) -> discord.ui.Select:
    return discord.ui.Select(custom_id=custom_id, required=False,
                             placeholder="Leave as it is" if current else "Leave unchanged",
                             options=[discord.SelectOption(label=l, value=v, default=v == current)
                                      for l, v in SHOW_HIDE])


def _show_hide(stored: str) -> str:
    return "show" if stored == "true" else "hide"


class SettingsForm(discord.ui.Modal):
    TITLES = {FULLBLESS: "Fullbless level", EXIVA: "Exiva lists", CHANNEL_FILTER: "Channel level filters",
              NEUTRAL: "Neutral players", COMMAND_LOG: "Command log", ONLINE_FILTER: "Online list filters",
              MASSLOG: "Mass log alert", MEMBER_ROLE: "Member role"}

    def __init__(self, action: str, worlds: list[WorldConfig]):
        super().__init__(title=self.TITLES[action], custom_id=f"settingsform:{action}", timeout=None)
        self.action, self.worlds = action, worlds
        only = worlds[0] if len(worlds) == 1 else None
        self.world = self.level = self.option = self.levels = self.deaths = self.channel = None
        self.online_inputs: dict[str, discord.ui.TextInput] = {}
        self.role: discord.ui.RoleSelect | None = None
        if action not in (COMMAND_LOG, MEMBER_ROLE) and len(worlds) > 1:
            self.world = discord.ui.Select(custom_id="world", placeholder="Pick a world", required=True,
                                           options=[discord.SelectOption(label=w.name, value=w.name) for w in worlds])
            self.add_item(discord.ui.Label(text="Which world?", description="The world this setting applies to.",
                                           component=self.world))
        if action == FULLBLESS:
            self.level = _number(only.fullbless_level if only else None, "250")
            self.add_item(discord.ui.Label(text="Fullbless level", component=self.level,
                                           description="Enemy deaths at or above this level ping the Fullbless role."))
        elif action == EXIVA:
            self.option = _choice("option", _show_hide(only.exiva_list) if only else None)
            self.add_item(discord.ui.Label(text="Exiva list on deaths", component=self.option,
                                           description="When an ally is killed, list who to exiva."))
        elif action == CHANNEL_FILTER:
            self.levels = _number(only.levels_min if only else None, "8")
            self.deaths = _number(only.deaths_min if only else None, "8")
            self.add_item(discord.ui.Label(text="Levels channel", description="Hide level-ups below this level.",
                                           component=self.levels))
            self.add_item(discord.ui.Label(text="Deaths channel", description="Hide deaths below this level.",
                                           component=self.deaths))
        elif action == NEUTRAL:
            self.levels = _choice("levels", _show_hide(only.show_neutral_levels) if only else None)
            self.deaths = _choice("deaths", _show_hide(only.show_neutral_deaths) if only else None)
            self.add_item(discord.ui.Label(text="Neutral levels", description="Level-ups by players you don't track.",
                                           component=self.levels))
            self.add_item(discord.ui.Label(text="Neutral deaths", description="Deaths of players you don't track.",
                                           component=self.deaths))
        elif action == ONLINE_FILTER:
            for column, text in (("online_enemies_min", "Enemies"), ("online_allies_min", "Allies")):
                self.online_inputs[column] = _number(getattr(only, column) if only else None, "0")
                self.add_item(discord.ui.Label(text=f"{text} in the online list", component=self.online_inputs[column],
                                               description=f"Hide {text.lower()} below this level; 0 shows everyone."))
        elif action == MASSLOG:
            current = masslog_mode(only) if only else None
            self.option = discord.ui.Select(
                custom_id="option", required=False, placeholder="Leave as it is",
                options=[discord.SelectOption(label=l, value=v, default=v == current) for l, v in MASSLOG_MODES])
            self.add_item(discord.ui.Label(text="When many enemies log in at once", component=self.option,
                                           description="Who the alert in the deaths channel pings."))
        elif action == MEMBER_ROLE:
            self.role = discord.ui.RoleSelect(custom_id="role", min_values=0, max_values=1, required=False,
                                              placeholder="Everyone (no member role)")
            self.add_item(discord.ui.Label(text="Your guild members' role", component=self.role,
                                           description="Only this role sees my channels and private rooms. "
                                                       "Leave empty: everyone sees them."))
        elif action == COMMAND_LOG:
            self.channel = discord.ui.ChannelSelect(custom_id="channel", channel_types=[discord.ChannelType.text],
                                                    placeholder="Pick a channel", min_values=1, max_values=1)
            self.add_item(discord.ui.Label(text="Command log channel", component=self.channel,
                                           description="Where the bot posts what was changed and by whom."))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        if not has_manage_server(interaction.user):
            await interaction.response.send_message(embed=_refusal(), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.action == COMMAND_LOG:
            await self._command_log(bot, interaction)
            return
        if self.action == MASSLOG:
            await self._masslog(bot, interaction)
            return
        if self.action == MEMBER_ROLE:
            await self._member_role(bot, interaction)
            return
        state = bot.state.guild(interaction.guild_id)
        name = self.worlds[0].name if len(self.worlds) == 1 else (self.world.values[0] if self.world.values else "")
        world = state.worlds.get(name)
        if world is None:
            await interaction.followup.send(embed=embeds.error("Pick a world first."), ephemeral=True)
            return
        changes, problem = self._changes()
        if problem:
            await interaction.followup.send(embed=embeds.error(problem), ephemeral=True)
            return
        changes = {c: v for c, v in changes.items() if getattr(world, c) != v}
        if not changes:
            await interaction.followup.send(embed=embeds.error("Nothing was changed."), ephemeral=True)
            return
        pool = await bot.db.guild(interaction.guild_id)
        for column, value in changes.items():
            await repos.update_world_setting(pool, world.name, column, value)
        bot.state.set_world(interaction.guild_id, dataclasses.replace(world, **changes))
        described = ", ".join(f"**{LABELS[c]}** → **{_shown(v)}**" for c, v in changes.items())
        await adminlog.post(interaction.guild, state.info,
                            f"{adminlog.user(interaction.user.name)} changed {described} for **{world.name}**.",
                            SETTINGS_THUMBNAIL)
        await interaction.followup.send(embed=embeds.response(f":gear: {described} for **{world.name}**."),
                                        ephemeral=True)

    def _changes(self) -> tuple[dict[str, str | int], str | None]:
        changes: dict[str, str | int] = {}

        def number(field: discord.ui.TextInput | None, column: str) -> str | None:
            raw = (field.value or "").strip() if field else ""
            if not raw:
                return None
            if not raw.isdigit():
                return f"`{raw}` isn't a level - use a whole number."
            changes[column] = int(raw)
            return None

        def choice(select: discord.ui.Select | None, column: str) -> None:
            if select is not None and select.values:
                changes[column] = "true" if select.values[0] == "show" else "false"

        problem = None
        if self.action == FULLBLESS:
            problem = number(self.level, "fullbless_level")
        elif self.action == EXIVA:
            choice(self.option, "exiva_list")
        elif self.action == CHANNEL_FILTER:
            problem = number(self.levels, "levels_min") or number(self.deaths, "deaths_min")
        elif self.action == NEUTRAL:
            choice(self.levels, "show_neutral_levels")
            choice(self.deaths, "show_neutral_deaths")
        elif self.action == ONLINE_FILTER:
            for column, field in self.online_inputs.items():
                problem = problem or number(field, column)
        return changes, problem

    async def _member_role(self, bot: TibiaBot, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        state = bot.state.guild(interaction.guild_id)
        if state.info is None:
            await interaction.followup.send(embed=embeds.error("Run `/init` first."), ephemeral=True)
            return
        picked = self.role.values[0] if self.role.values else None
        role = guild.get_role(picked.id) if picked else None
        if role is not None and role == guild.default_role:
            role = None  # @everyone is the same as no member role
        previous = guild.get_role(int(state.info.member_role)) if (state.info.member_role or "").isdigit() else None
        state.info.member_role = str(role.id) if role else "0"
        await repos.save_discord_info(await bot.db.guild(interaction.guild_id), state.info)
        failed = await visibility.apply(guild, state.info, list(state.worlds.values()), role, previous)
        for world in state.worlds.values():
            if masslog_mode(world) == MASSLOG_MEMBERS:
                await refresh_role_panel(guild, state.info, world)
        shown = role.mention if role else "**everyone**"
        await adminlog.post(guild, state.info,
                            f"{adminlog.user(interaction.user.name)} set the member role to {shown}.",
                            SETTINGS_THUMBNAIL)
        text = (f"My channels are now visible to {shown} only (the command log stays admin-only), and new "
                f"`/privateroom` channels can be seen by them; only the party can join."
                if role else "My channels are visible to everyone again; private rooms are party-only.")
        if failed:
            text += (f"\n\n{emojis.get('no')} Discord refused changing: {', '.join(failed)}. Check my role has "
                     "**Manage Roles** and sits above that role.")
        if role is None and any(masslog_mode(w) == MASSLOG_MEMBERS for w in state.worlds.values()):
            text += "\n\nMass log alerts set to ping the member role will now post without a ping."
        await interaction.followup.send(embed=embeds.ok(text), ephemeral=True)

    async def _masslog(self, bot: TibiaBot, interaction: discord.Interaction) -> None:
        state = bot.state.guild(interaction.guild_id)
        name = self.worlds[0].name if len(self.worlds) == 1 else (self.world.values[0] if self.world.values else "")
        world = state.worlds.get(name)
        mode = self.option.values[0] if self.option.values else None
        if world is None or mode is None:
            await interaction.followup.send(embed=embeds.error("Pick a world and an option."), ephemeral=True)
            return
        if mode == "role":
            guild = interaction.guild
            current = guild.get_role(int(world.masslog_role)) if world.masslog_role.isdigit() else None
            role_name = f"{world.name} Masslog"
            role = current or discord.utils.get(guild.roles, name=role_name)
            try:
                role = role or await guild.create_role(name=role_name, color=MASSLOG_COLOR, reason="Mass log alerts")
            except discord.Forbidden:
                await interaction.followup.send(embed=embeds.error("I need **Manage Roles** to create that role."),
                                                ephemeral=True)
                return
            value = str(role.id)
        elif mode == "members":
            if not (state.info and (state.info.member_role or "").isdigit() and state.info.member_role != "0"):
                await interaction.followup.send(embed=embeds.error(
                    "Set your member role first: `/settings` → **Member Role**."), ephemeral=True)
                return
            value = MASSLOG_MEMBERS
        else:
            value = MASSLOG_EVERYONE if mode == "everyone" else "0"
        await repos.update_world_setting(await bot.db.guild(interaction.guild_id), world.name, "masslog_role", value)
        world = dataclasses.replace(world, masslog_role=value)
        bot.state.set_world(interaction.guild_id, world)
        await refresh_role_panel(interaction.guild, state.info, world)
        shown = dict((v, l) for l, v in MASSLOG_MODES)[mode]
        await adminlog.post(interaction.guild, state.info,
                            f"{adminlog.user(interaction.user.name)} set **mass log alerts** to **{shown}** for "
                            f"**{world.name}**.", SETTINGS_THUMBNAIL)
        await interaction.followup.send(embed=embeds.response(
            f":gear: Mass log alerts for **{world.name}**: **{shown}**."), ephemeral=True)

    async def _command_log(self, bot: TibiaBot, interaction: discord.Interaction) -> None:
        picked = self.channel.values[0] if self.channel.values else None
        channel = interaction.guild.get_channel(picked.id) if picked else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(embed=embeds.error("Pick a text channel in this server."), ephemeral=True)
            return
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.followup.send(embed=embeds.error(
                f"I can't post in {channel.mention}. Give me **View Channel**, **Send Messages** and "
                "**Embed Links** there first."), ephemeral=True)
            return
        state = bot.state.guild(interaction.guild_id)
        if state.info is None:
            await interaction.followup.send(embed=embeds.error("Run `/init` first."), ephemeral=True)
            return
        state.info.admin_channel = str(channel.id)
        await repos.save_discord_info(await bot.db.guild(interaction.guild_id), state.info)
        await adminlog.post(interaction.guild, state.info,
                            f"{adminlog.user(interaction.user.name)} moved the command log here.", SETTINGS_THUMBNAIL)
        await interaction.followup.send(embed=embeds.ok(f"The command log now goes to {channel.mention}."),
                                        ephemeral=True)


LABELS = {"fullbless_level": "Fullbless level", "exiva_list": "Exiva list", "levels_min": "Levels minimum",
          "deaths_min": "Deaths minimum", "show_neutral_levels": "Neutral levels",
          "show_neutral_deaths": "Neutral deaths", "online_enemies_min": "Online enemies minimum",
          "online_allies_min": "Online allies minimum", "online_neutrals_min": "Online others minimum"}


def _shown(value: str | int) -> str:
    return {"true": "show", "false": "hide"}.get(value, str(value)) if isinstance(value, str) else str(value)


# --- role opt-in buttons ----------------------------------------------------

ROLE_BUTTONS = (("fullbless_role", "inq", discord.ButtonStyle.success),
                ("nemesis_role", "boss", discord.ButtonStyle.primary),
                ("allypk_role", "hazard", discord.ButtonStyle.danger),
                ("masslog_role", "masslog", discord.ButtonStyle.secondary))
MASSLOG_COLOR = discord.Color.from_rgb(219, 175, 72)


def role_panel(world: WorldConfig, member_role: str = "0") -> tuple[discord.Embed, discord.ui.View]:
    e = emojis.get
    lines = [f"{e('inq')}<@&{world.fullbless_role}> If an enemy fullblesses and is over level "
             f"`{world.fullbless_level}`",
             f"{e('boss')}<@&{world.nemesis_role}> If anyone dies to a rare boss",
             f"{e('hazard')}<@&{world.allypk_role}> If an ally gets pked"]
    mode = masslog_mode(world)
    if mode == "role":
        lines.append(f"{e('masslog') or '⚡'}<@&{world.masslog_role}> If many enemies log in at once")
    elif mode == "everyone":
        lines.append(f"{e('masslog') or '⚡'} Mass logs ping **everyone** here (change in `/settings`)")
    elif mode == "members" and member_role.isdigit() and member_role != "0":
        lines.append(f"{e('masslog') or '⚡'} Mass logs ping <@&{member_role}> (change in `/settings`)")
    embed = discord.Embed(title=f":crossed_swords: {world.name} :crossed_swords:", color=embeds.BRAND_COLOR,
                          url=f"https://www.tibia.com/community/?subtopic=worlds&world={world.name}",
                          description="\n".join(lines))
    embed.set_footer(text="Press a button to get or drop that role:")
    view = discord.ui.View(timeout=None)
    for column, emoji_name, style in ROLE_BUTTONS:
        if column == "masslog_role" and mode != "role":
            continue
        view.add_item(RoleButton(column, world.name, emoji=e(emoji_name) or "⚡", style=style))
    return embed, view


async def find_role_panel(channel: discord.TextChannel, world: WorldConfig) -> discord.Message | None:
    marker = f"role:fullbless_role:{world.name}"
    try:
        async for message in channel.history(limit=50):
            if message.author.id == channel.guild.me.id and any(
                    getattr(child, "custom_id", None) == marker
                    for row in message.components for child in getattr(row, "children", [])):
                return message
    except discord.HTTPException:
        pass
    return None


async def post_role_panel(channel: discord.TextChannel, world: WorldConfig, existing: discord.Message | None = None,
                          member_role: str = "0") -> None:
    """Edit the world's panel in place when there is one, else post it."""
    embed, view = role_panel(world, member_role)
    try:
        if existing:
            await existing.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        else:
            await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        log.warning("Could not post the role panel in %s: %s", channel.guild.id, e)


async def refresh_role_panel(guild: discord.Guild, info, world: WorldConfig) -> None:
    channel = guild.get_channel(int(info.boosted_channel)) if info and info.boosted_channel.isdigit() else None
    if isinstance(channel, discord.TextChannel):
        await post_role_panel(channel, world, await find_role_panel(channel, world), info.member_role or "0")


class RoleButton(discord.ui.DynamicItem[discord.ui.Button],
                 template=r"role:(?P<column>fullbless_role|nemesis_role|allypk_role|masslog_role):(?P<world>[A-Za-z]+)"):
    def __init__(self, column: str, world: str, *, emoji: str | None = None,
                 style: discord.ButtonStyle = discord.ButtonStyle.secondary):
        super().__init__(discord.ui.Button(custom_id=f"role:{column}:{world}", emoji=emoji, style=style))
        self.column, self.world = column, world

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match):
        return cls(match["column"], match["world"])

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        world = bot.state.guild(interaction.guild_id).worlds.get(self.world)
        role_id = getattr(world, self.column) if world else ""
        role = interaction.guild.get_role(int(role_id)) if role_id.isdigit() else None
        member = interaction.user
        if role is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(embed=embeds.error(
                "That role is gone - ask an admin to run `/repair`."), ephemeral=True)
            return
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="role button")
                text = f":gear: You have been removed from the {role.mention} role."
            else:
                await member.add_roles(role, reason="role button")
                text = f":gear: You have been added to the {role.mention} role."
        except discord.Forbidden:
            text = (f"{emojis.get('no')} I can't manage {role.mention}. An admin needs to move my role above it in "
                    "Server Settings → Roles.")
        await interaction.response.send_message(embed=embeds.response(text), ephemeral=True)


class SettingsCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot

    @app_commands.command(name="settings", description="Change what the deaths and levels channels show")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def settings(self, interaction: discord.Interaction) -> None:
        if not has_manage_server(interaction.user):
            await interaction.response.send_message(embed=_refusal(), ephemeral=True)
            return
        worlds = sorted(self.bot.state.guild(interaction.guild_id).worlds)
        if not worlds:
            await interaction.response.send_message(
                embed=embeds.error("No worlds are set up here yet — run `/init` first."), ephemeral=True)
            return
        embed = discord.Embed(title="Server settings", color=embeds.BRAND_COLOR, description=(
            "Pick what you want to change. Each one opens a form showing what it is set to now, so you can check "
            f"a setting without changing it.\n\nTracking: {', '.join(f'**{w}**' for w in worlds)}\n\n"
            "Enemy and ally filters are under `/hunted` and `/allies` → **Config**."))
        await interaction.response.send_message(embed=embed, view=settings_view(), ephemeral=True)


async def setup(bot: TibiaBot) -> None:
    bot.add_dynamic_items(SettingsButton, RoleButton)
    await bot.add_cog(SettingsCog(bot))
