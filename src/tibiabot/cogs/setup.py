"""`/init`, `/repair` and `/remove`: the channels, roles and config rows for a world.

Same names, layout and stored ids as the Scala bot's ChannelService, minus what
is not ported (Patreon seats, boosted/Galthen posts, the activity channel, the
respawn forum, mass-log and bounty roles).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from tibiabot import embeds
from tibiabot.db import repos
from tibiabot.db.repos import NONE_ID, WorldConfig
from tibiabot.cogs.settings import find_role_panel, post_role_panel

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

ADMIN_CATEGORY = "Popaco Bot"
COMMAND_LOG = "🖥️・ᴄᴏᴍᴍᴀɴᴅ ʟᴏɢ"
NOTIFICATIONS = "👑・ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴs"
ONLINE = "📈・ᴏɴʟɪɴᴇ"
DEATHS = "💀・ᴅᴇᴀᴛʜs"
LEVELS = "💖・ʟᴇᴠᴇʟs"
STATISTICS = "📊・sᴛᴀᴛɪsᴛɪᴄs"
MODERATOR_ROLE = "Popaco Bot Moderator"

# (worlds column, role name suffix, colour)
WORLD_ROLES = (
    ("fullbless_role", "Fullbless", discord.Color.from_rgb(0, 156, 70)),
    ("nemesis_role", "Rare Boss", discord.Color.from_rgb(164, 76, 230)),
    ("allypk_role", "PVP", discord.Color.from_rgb(220, 0, 0)),
    ("masslog_role", "Masslog", discord.Color.from_rgb(219, 175, 72)),
)
# (worlds column, channel name, intro text or None)
WORLD_CHANNELS = (
    ("allies_channel", ONLINE, None),
    ("deaths_channel", DEATHS, ":speech_balloon: This channel shows deaths that occur on this world.\n\n"
                               "You can filter what appears in this channel using **`/settings`**."),
    ("levels_channel", LEVELS, ":speech_balloon: This channel shows levels that have been gained on this world.\n\n"
                               "You can filter what appears in this channel using **`/settings`**."),
    ("statistics_channel", STATISTICS, ":speech_balloon: This channel gets a daily summary of the world after "
                                       "server save, including which rare bosses are likely to spawn today."),
)

WORLD_BOT_PERMS = discord.PermissionOverwrite(
    view_channel=True, send_messages=True, mention_everyone=True, embed_links=True,
    read_message_history=True, manage_channels=True)
EVERYONE_READ_ONLY = discord.PermissionOverwrite(send_messages=False)
# Discord refuses an overwrite that allows anything the bot doesn't hold itself
# (and Manage Permissions in an overwrite needs Administrator), so overwrites
# only ever repeat permissions from the invite link.
ADMIN_BOT_PERMS = discord.PermissionOverwrite(
    view_channel=True, send_messages=True, read_message_history=True, embed_links=True,
    manage_channels=True)
REQUIRED = ("manage_roles", "manage_channels", "view_channel", "send_messages", "embed_links",
            "read_message_history", "mention_everyone")


def missing_permissions(member: discord.Member) -> list[str]:
    perms = member.guild_permissions
    if perms.administrator:
        return []
    return [p.replace("_", " ").title() for p in REQUIRED if not getattr(perms, p)]


class SetupCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot

    # --- helpers -------------------------------------------------------------

    async def _resolve_world(self, interaction: discord.Interaction, world: str) -> str | None:
        resolved = await self.bot.world_list.resolve(world)
        if resolved is None:
            await interaction.followup.send(embed=embeds.error("This is not a valid World on Tibia."))
        return resolved

    @staticmethod
    async def _role(guild: discord.Guild, name: str, color: discord.Color) -> discord.Role:
        existing = discord.utils.find(lambda r: r.name.lower() == name.lower(), guild.roles)
        return existing or await guild.create_role(name=name, color=color, reason="Tibia bot /init")

    @staticmethod
    async def _category(guild: discord.Guild, name: str, overwrites) -> discord.CategoryChannel:
        """Reuse a category of this name (left by an interrupted run) or create it."""
        existing = discord.utils.get(guild.categories, name=name)
        return existing or await guild.create_category(name, overwrites=overwrites)

    @staticmethod
    async def _text_channel(guild: discord.Guild, category: discord.CategoryChannel, name: str,
                            overwrites) -> tuple[discord.TextChannel, bool]:
        """(channel, created). Reuses a channel of this name already in the category."""
        existing = discord.utils.get(category.text_channels, name=name)
        if existing:
            return existing, False
        return await guild.create_text_channel(name, category=category, overwrites=overwrites), True

    async def _admin_area(self, guild: discord.Guild, pool) -> repos.DiscordInfo:
        """The bot's own category with the command log and notifications channels,
        created or re-created piece by piece as needed."""
        info = await repos.get_discord_info(pool)
        category = guild.get_channel(int(info.admin_category)) if info and info.admin_category.isdigit() else None
        if not isinstance(category, discord.CategoryChannel):
            category = await self._category(guild, ADMIN_CATEGORY, {
                guild.me: ADMIN_BOT_PERMS,
                guild.default_role: discord.PermissionOverwrite(view_channel=True),
            })
        elif category.name != ADMIN_CATEGORY:
            # A server set up under the bot's old name keeps its category, renamed.
            await category.edit(name=ADMIN_CATEGORY)
        admin = guild.get_channel(int(info.admin_channel)) if info and info.admin_channel.isdigit() else None
        if not isinstance(admin, discord.TextChannel):
            admin, _ = await self._text_channel(guild, category, COMMAND_LOG, {
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
            })
        notes = guild.get_channel(int(info.boosted_channel)) if info and info.boosted_channel.isdigit() else None
        if not isinstance(notes, discord.TextChannel):
            notes, _ = await self._text_channel(guild, category, NOTIFICATIONS, {
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
                guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            })
        owner = guild.owner.display_name if guild.owner else "Not Available"
        if info is None:
            info = repos.new_discord_info(guild.name, owner, str(category.id), str(admin.id), str(notes.id))
        else:
            info.guild_name, info.guild_owner = guild.name, owner
            info.admin_category, info.admin_channel, info.boosted_channel = str(category.id), str(admin.id), str(notes.id)
        await repos.save_discord_info(pool, info)
        return info

    async def _ensure_role_panel(self, guild: discord.Guild, info: repos.DiscordInfo | None,
                                 world: WorldConfig) -> bool:
        """Post the world's role opt-in buttons in the notifications channel, or bring
        an existing panel up to date. True when a new one was posted."""
        channel = guild.get_channel(int(info.boosted_channel)) if info and info.boosted_channel.isdigit() else None
        if not isinstance(channel, discord.TextChannel):
            return False
        existing = await find_role_panel(channel, world)
        await post_role_panel(channel, world, existing)
        return existing is None

    async def _moderator_role(self, guild: discord.Guild, pool) -> None:
        try:
            info = await repos.get_discord_info(pool)
            stored = guild.get_role(int(info.moderator_role)) if info and (info.moderator_role or "").isdigit() else None
            if stored and stored.name != MODERATOR_ROLE:
                await stored.edit(name=MODERATOR_ROLE)
            role = stored or await self._role(guild, MODERATOR_ROLE, discord.Color.from_rgb(114, 137, 218))
            await repos.set_moderator_role(pool, str(role.id))
        except discord.HTTPException as e:
            log.warning("Could not create the moderator role in %s: %s", guild.id, e)

    async def _admin_log(self, guild: discord.Guild, text: str) -> None:
        info = self.bot.state.guild(guild.id).info
        channel = guild.get_channel(int(info.admin_channel)) if info and info.admin_channel.isdigit() else None
        if isinstance(channel, discord.TextChannel):
            embed = embeds.response(text)
            embed.set_thumbnail(url=f"{embeds.WIKI_FILE}Hammer.gif")
            await channel.send(embed=embed)

    async def _remove_admin_area(self, guild: discord.Guild, pool) -> None:
        """The last world is gone, so the bot's own category goes with it."""
        info = await repos.get_discord_info(pool)
        if info is None:
            return
        for channel_id in (info.boosted_channel, info.admin_channel, info.admin_category):
            channel = guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
            if channel:
                try:
                    await channel.delete(reason="last world removed")
                except discord.HTTPException as e:
                    log.warning("Could not delete %s in %s: %s", channel_id, guild.id, e)
        self.bot.state.guild(guild.id).info = None

    @staticmethod
    def _missing_text(missing: list[str]) -> str:
        return ("I'm missing these server permissions: " + ", ".join(f"**{m}**" for m in missing)
                + ".\nServer Settings → Roles → my role → turn them on, or re-invite me with the link from the README.")

    @staticmethod
    def _protected_channels(world: WorldConfig) -> set[int]:
        ids = [world.allies_channel, world.enemies_channel, world.neutrals_channel, world.levels_channel,
               world.deaths_channel, world.statistics_channel, world.activity_channel]
        return {int(i) for i in ids if i and i.isdigit() and i != NONE_ID}

    # --- commands ------------------------------------------------------------

    @app_commands.command(name="init", description="Start tracking a world: creates its channels and roles")
    @app_commands.describe(world="The world you want to track")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def init_world(self, interaction: discord.Interaction, world: str) -> None:
        await interaction.response.defer(thinking=True)
        guild = interaction.guild
        name = await self._resolve_world(interaction, world)
        if name is None:
            return
        if missing := missing_permissions(guild.me):
            await interaction.followup.send(embed=embeds.error(self._missing_text(missing)))
            return
        try:
            pool = await self.bot.db.init_guild(guild.id)
            if await repos.get_world(pool, name):
                await interaction.followup.send(embed=embeds.error(
                    f"The channels for **{name}** have already been setup.\n"
                    f"Use `/repair` if you need to recreate channels for **{name}** that you have deleted."))
                return
            roles = {col: await self._role(guild, f"{name} {suffix}", color) for col, suffix, color in WORLD_ROLES}
            info = await self._admin_area(guild, pool)
            category = await self._category(guild, name, {guild.me: WORLD_BOT_PERMS,
                                                          guild.default_role: EVERYONE_READ_ONLY})
            channels: dict[str, discord.TextChannel] = {}
            for col, channel_name, intro in WORLD_CHANNELS:
                channels[col], created = await self._text_channel(guild, category, channel_name, {
                    guild.me: WORLD_BOT_PERMS, guild.default_role: EVERYONE_READ_ONLY})
                if intro and created:
                    await channels[col].send(embed=embeds.channel_intro(intro))
            config = WorldConfig(
                name=name, allies_channel=str(channels["allies_channel"].id), enemies_channel=NONE_ID,
                neutrals_channel=NONE_ID, levels_channel=str(channels["levels_channel"].id),
                deaths_channel=str(channels["deaths_channel"].id), category=str(category.id),
                fullbless_role=str(roles["fullbless_role"].id), nemesis_role=str(roles["nemesis_role"].id),
                allypk_role=str(roles["allypk_role"].id), masslog_role=str(roles["masslog_role"].id),
                statistics_channel=str(channels["statistics_channel"].id))
            await repos.save_world(pool, config)
            await self._moderator_role(guild, pool)
            await self._ensure_role_panel(guild, info, config)
            state = self.bot.state.guild(guild.id)
            state.info = await repos.get_discord_info(pool) or info
            self.bot.state.set_world(guild.id, config)
            await self.bot.pollers.sync(self.bot.state.tracked_worlds())
        except discord.Forbidden as e:
            log.warning("/init %s on %s refused by Discord: %s", name, guild.id, e)
            await interaction.followup.send(embed=embeds.error(
                f"Discord refused part of setting up **{name}** ({e.text or 'Missing Permissions'}). "
                f"Check that my role is above the roles I create, then run `/init {name}` again; "
                "it reuses whatever was already made."))
            return
        await self._admin_log(guild, f"**{interaction.user.display_name}** has run `/init` for the world **{name}** "
                                     "and created its channels.")
        await interaction.followup.send(embed=embeds.response(
            f":gear: The channels for **{name}** have been configured successfully.\n"
            f"⚠️ *You should probably mute the <#{config.levels_channel}> channel*"))

    @app_commands.command(name="repair", description="Repair & recreate channels that have been deleted for a specific world")
    @app_commands.describe(world="What world are you trying to recreate channels for?")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def repair(self, interaction: discord.Interaction, world: str) -> None:
        await interaction.response.defer(thinking=True)
        guild = interaction.guild
        name = await self._resolve_world(interaction, world)
        if name is None:
            return
        if missing := missing_permissions(guild.me):
            await interaction.followup.send(embed=embeds.error(self._missing_text(missing)))
            return
        try:
            pool = await self.bot.db.init_guild(guild.id)
            config = await repos.get_world(pool, name)
            if config is None:
                await interaction.followup.send(embed=embeds.error(
                    f"The world **{name}** is not configured here. Use `/init {name}` first."))
                return
            fixed: list[str] = []
            info = await self._admin_area(guild, pool)
            for col, suffix, color in WORLD_ROLES:
                role_id = getattr(config, col)
                if col == "masslog_role" and not (role_id.isdigit() and role_id != "0"):
                    continue  # "everyone" or turned off in /settings: nothing to repair
                if not (role_id.isdigit() and guild.get_role(int(role_id))):
                    role = await self._role(guild, f"{name} {suffix}", color)
                    await repos.update_world_column(pool, name, col, str(role.id))
                    fixed.append(role.mention)
            category = guild.get_channel(int(config.category)) if config.category.isdigit() else None
            if not isinstance(category, discord.CategoryChannel):
                category = await guild.create_category(name, overwrites={guild.me: WORLD_BOT_PERMS,
                                                                         guild.default_role: EVERYONE_READ_ONLY})
                await repos.update_world_column(pool, name, "category", str(category.id))
                fixed.append(f"**{name}** category")
            for col, channel_name, intro in WORLD_CHANNELS:
                channel_id = getattr(config, col)
                channel = guild.get_channel(int(channel_id)) if channel_id.isdigit() else None
                if isinstance(channel, discord.TextChannel):
                    if channel.category_id != category.id:
                        await channel.edit(category=category)
                    continue
                channel = await guild.create_text_channel(channel_name, category=category, overwrites={
                    guild.me: WORLD_BOT_PERMS, guild.default_role: EVERYONE_READ_ONLY})
                if intro:
                    await channel.send(embed=embeds.channel_intro(intro))
                await repos.update_world_column(pool, name, col, str(channel.id))
                fixed.append(channel.mention)
            await self._moderator_role(guild, pool)
            state = self.bot.state.guild(guild.id)
            state.info = await repos.get_discord_info(pool) or info
            config = await repos.get_world(pool, name)
            self.bot.state.set_world(guild.id, config)
            if await self._ensure_role_panel(guild, state.info, config):
                fixed.append("role buttons")
        except discord.Forbidden as e:
            log.warning("/repair %s on %s missing a permission: %s", name, guild.id, e)
            await interaction.followup.send(embed=embeds.error(
                "I'm missing a required permission. Grant me **Manage Roles**, **Manage Channels** "
                "and **Manage Permissions**, then try again."))
            return
        if fixed:
            await self._admin_log(guild, f"**{interaction.user.display_name}** has run `/repair` on **{name}**.")
            await interaction.followup.send(embed=embeds.response(
                f":tools: Recreated for **{name}**: {', '.join(fixed)}"))
        else:
            await interaction.followup.send(embed=embeds.ok(f"Nothing was missing for **{name}**."))

    @app_commands.command(name="remove", description="Remove a world from being tracked")
    @app_commands.describe(world="The world you want to remove")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def remove(self, interaction: discord.Interaction, world: str) -> None:
        await interaction.response.defer(thinking=True)
        guild = interaction.guild
        name = await self._resolve_world(interaction, world)
        if name is None:
            return
        if not await self.bot.db.guild_exists(guild.id):
            await interaction.followup.send(embed=embeds.error(f"The world **{name}** is not configured here."))
            return
        pool = await self.bot.db.guild(guild.id)
        config = await repos.get_world(pool, name)
        if config is None:
            await interaction.followup.send(embed=embeds.error(f"The world **{name}** is not configured here."))
            return
        if interaction.channel_id in self._protected_channels(config):
            await interaction.followup.send(embed=embeds.error(
                "That command would delete this channel, run it somewhere else."))
            return
        try:
            for col, _, _ in WORLD_ROLES:
                role_id = getattr(config, col)
                role = guild.get_role(int(role_id)) if role_id.isdigit() else None
                if role:
                    await role.delete(reason=f"/remove {name}")
            for channel_id in self._protected_channels(config) | ({int(config.category)} if config.category.isdigit() else set()):
                channel = guild.get_channel(channel_id)
                if channel:
                    await channel.delete(reason=f"/remove {name}")
        except discord.Forbidden:
            await interaction.followup.send(embed=embeds.error(
                f"I couldn't finish removing **{name}** because I'm missing a required permission. "
                f"Grant me **Manage Channels** and **Manage Roles**, then run `/remove {name}` again."))
            return
        await repos.delete_world(pool, name)
        self.bot.state.remove_world(guild.id, name)
        await self.bot.pollers.sync(self.bot.state.tracked_worlds())
        if not self.bot.state.guild(guild.id).worlds:
            await self._remove_admin_area(guild, pool)
            await interaction.followup.send(embed=embeds.response(f":gear: The world **{name}** has been removed."))
            return
        await self._admin_log(guild, f"**{interaction.user.display_name}** has run `/remove` on the world "
                                     f"**{name}** and deleted its channels.")
        await interaction.followup.send(embed=embeds.response(f":gear: The world **{name}** has been removed."))

    @init_world.autocomplete("world")
    @repair.autocomplete("world")
    @remove.autocomplete("world")
    async def _world_autocomplete(self, interaction: discord.Interaction, current: str):
        if interaction.command and interaction.command.name in ("repair", "remove"):
            names = sorted(self.bot.state.guild(interaction.guild_id).worlds)
        else:
            names = await self.bot.world_list.names()
        current = current.lower()
        return [app_commands.Choice(name=n, value=n) for n in names if current in n.lower()][:25]


async def setup(bot: TibiaBot) -> None:
    await bot.add_cog(SetupCog(bot))
