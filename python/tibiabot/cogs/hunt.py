"""`/hunt`: a private voice channel for one party.

The form picks the party; the bot creates a voice channel only they can see,
moves whoever is already in voice into it, pings the rest there, and deletes
the channel once it has been empty for a minute or someone presses End hunt.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from tibiabot import embeds
from tibiabot.cogs.watchdog import WATCHDOG_URL, room_name
from tibiabot.permissions import is_moderator

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

log = logging.getLogger(__name__)

HUNT_PREFIX = "🏹・Hunt"
EMPTY_GRACE = 60          # seconds an emptied hunt channel waits before it goes
NEVER_JOINED_GRACE = 600  # a hunt nobody ever joined is removed after this
MAX_PARTY = 25


def channel_name(name: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", (name or "").strip())[:60]
    return f"{HUNT_PREFIX} – {cleaned}" if cleaned else HUNT_PREFIX


def party_overwrites(guild: discord.Guild, party: list[discord.Member], viewers: discord.Role | None = None) -> dict:
    """Only the party can join and talk; `viewers` (the role picked in /settings)
    can see the channel and who is in it."""
    allowed = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, stream=True,
                                          send_messages=True, read_message_history=True, use_voice_activation=True)
    overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
                  # Only what the invite already grants the bot: Discord refuses an overwrite
                  # allowing anything the bot doesn't hold itself.
                  guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                        embed_links=True, read_message_history=True)}
    if viewers is not None and viewers != guild.default_role:
        overwrites[viewers] = discord.PermissionOverwrite(view_channel=True, read_message_history=True,
                                                          connect=False)
    for member in party:
        overwrites[member] = allowed
    return overwrites


class HuntForm(discord.ui.Modal, title="Start a hunt"):
    def __init__(self, invoker: discord.Member):
        super().__init__(timeout=600)
        self.party = discord.ui.UserSelect(custom_id="party", min_values=1, max_values=MAX_PARTY, required=True,
                                           placeholder="Pick the party members",
                                           default_values=[discord.Object(id=invoker.id)])
        self.add_item(discord.ui.Label(text="Party", description="Who is hunting? You're already in.",
                                       component=self.party))
        self.hunt_name = discord.ui.TextInput(style=discord.TextStyle.short, required=False, max_length=60,
                                              placeholder="e.g. Asura, Library, Feru")
        self.add_item(discord.ui.Label(text="Name", description="Optional: names the channel.",
                                       component=self.hunt_name))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        cog: HuntCog | None = bot.get_cog("HuntCog")  # type: ignore[assignment]
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        members = [m for m in self.party.values if isinstance(m, discord.Member) and not m.bot]
        if interaction.user.id not in {m.id for m in members}:
            members.insert(0, interaction.user)
        name = (self.hunt_name.value or "").strip() or None
        category = getattr(interaction.channel, "category", None)
        info = bot.state.guild(guild.id).info
        viewers = guild.get_role(int(info.hunt_role)) if info and (info.hunt_role or "").isdigit() else None
        try:
            channel = await guild.create_voice_channel(channel_name(name), category=category,
                                                       overwrites=party_overwrites(guild, members, viewers),
                                                       reason=f"/hunt by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(embed=embeds.error(
                "I can't create channels here. Give me **Manage Channels**."), ephemeral=True)
            return
        cog.track(channel)

        moved, not_in_voice, failed = [], [], []
        can_move = guild.me.guild_permissions.move_members
        for member in members:
            current = guild.get_member(member.id) or member
            if current.voice is None or current.voice.channel is None:
                not_in_voice.append(member)
            elif not can_move:
                failed.append(member)
            else:
                try:
                    await current.move_to(channel, reason="/hunt")
                    moved.append(member)
                except discord.HTTPException:
                    failed.append(member)

        watchdog = WATCHDOG_URL + room_name(name)
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Watchdog", url=watchdog, emoji="🐶"))
        view.add_item(EndHuntButton(channel.id))
        await channel.send(
            content=" ".join(m.mention for m in members),
            embed=discord.Embed(
                title=f"🏹 {name or 'Hunt'}", color=embeds.BRAND_COLOR,
                description=(f"Party of **{len(members)}**, started by {interaction.user.mention}.\n"
                             f"Watchdog room: {watchdog}\n\nThis channel disappears a minute after everyone "
                             "has left, or when someone presses **End hunt**.")),
            view=view, allowed_mentions=discord.AllowedMentions(users=members))

        lines = [f"Created {channel.mention}."]
        if moved:
            lines.append(f"Moved: {', '.join(m.mention for m in moved)}")
        if not_in_voice:
            lines.append(f"Not in voice, pinged in the channel: {', '.join(m.mention for m in not_in_voice)}")
        if failed:
            lines.append(f"Couldn't move: {', '.join(m.mention for m in failed)}"
                         + ("" if can_move else " — give me the **Move Members** permission to move people."))
        await interaction.followup.send(embed=embeds.ok("\n".join(lines)), ephemeral=True)
        cog.expire_if_never_joined(channel)


class EndHuntButton(discord.ui.DynamicItem[discord.ui.Button], template=r"hunt:end:(?P<channel>[0-9]+)"):
    def __init__(self, channel_id: int):
        super().__init__(discord.ui.Button(custom_id=f"hunt:end:{channel_id}", label="End hunt", emoji="🏁",
                                           style=discord.ButtonStyle.danger))
        self.channel_id = channel_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match):
        return cls(int(match["channel"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        bot: TibiaBot = interaction.client  # type: ignore[assignment]
        channel = interaction.guild.get_channel(self.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(embed=embeds.error("That hunt is already over."), ephemeral=True)
            return
        info = bot.state.guild(interaction.guild_id).info
        in_party = channel.permissions_for(interaction.user).connect
        if not (in_party or is_moderator(interaction.user, info.moderator_role if info else None)):
            await interaction.response.send_message(embed=embeds.error("Only the party can end this hunt."),
                                                    ephemeral=True)
            return
        await interaction.response.send_message(embed=embeds.ok("Ending the hunt."), ephemeral=True)
        await bot.get_cog("HuntCog").delete(channel, f"ended by {interaction.user}")


class HuntCog(commands.Cog):
    def __init__(self, bot: TibiaBot):
        self.bot = bot
        self.hunts: set[int] = set()
        self._pending: dict[int, asyncio.Task] = {}

    def track(self, channel: discord.VoiceChannel) -> None:
        self.hunts.add(channel.id)

    async def delete(self, channel: discord.VoiceChannel, reason: str) -> None:
        self.hunts.discard(channel.id)
        task = self._pending.pop(channel.id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        try:
            await channel.delete(reason=f"Hunt over: {reason}")
        except discord.NotFound:
            pass
        except discord.HTTPException as e:
            log.warning("Could not delete hunt channel %s: %s", channel.id, e)

    def _delete_later(self, channel: discord.VoiceChannel, delay: float, reason: str) -> None:
        old = self._pending.pop(channel.id, None)
        if old:
            old.cancel()

        async def wait_then_delete() -> None:
            await asyncio.sleep(delay)
            fresh = channel.guild.get_channel(channel.id)
            if isinstance(fresh, discord.VoiceChannel) and not fresh.members:
                await self.delete(fresh, reason)

        self._pending[channel.id] = asyncio.create_task(wait_then_delete(), name=f"hunt-expire:{channel.id}")

    def expire_if_never_joined(self, channel: discord.VoiceChannel) -> None:
        if not channel.members:
            self._delete_later(channel, NEVER_JOINED_GRACE, "nobody joined")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState,
                                    after: discord.VoiceState) -> None:
        if after.channel and after.channel.id in self.hunts:
            task = self._pending.pop(after.channel.id, None)
            if task:
                task.cancel()
        left = before.channel
        if left and left.id in self.hunts and left != after.channel and not left.members:
            self._delete_later(left, EMPTY_GRACE, "everyone left")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Hunts outlive a restart: keep tracking the busy ones, clear out the empty ones."""
        for guild in self.bot.guilds:
            for channel in guild.voice_channels:
                if channel.name.startswith(HUNT_PREFIX):
                    self.track(channel)
                    if not channel.members:
                        self._delete_later(channel, EMPTY_GRACE, "empty after a restart")

    @app_commands.command(name="hunt", description="Start a hunt: a private voice channel for your party")
    @app_commands.guild_only()
    async def hunt(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(HuntForm(interaction.user))


async def setup(bot: TibiaBot) -> None:
    bot.add_dynamic_items(EndHuntButton)
    await bot.add_cog(HuntCog(bot))
