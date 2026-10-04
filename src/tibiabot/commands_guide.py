"""The 📖 commands channel in the bot's category: every command, grouped by who can
use it, plus what the channels show. Posted by /init and /repair, refreshed on startup."""

from __future__ import annotations

import discord

from tibiabot import embeds

# (heading, [(command, explanation)]). tests/test_commands_guide.py fails when a registered
# command is missing here, so this list can't fall behind the bot.
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Everyone", [
        ("split", "Paste the party hunt analyser from the Tibia client; get who pays whom, as ready-to-type "
                      "`transfer` commands."),
        ("bosses", "Which rare bosses are due to spawn today on your worlds, from daily kill statistics."),
        ("watchdog", "Post a TibiaCardinal Watchdog room link for your party. Optional `name`."),
        ("privatehunt", "Pick your party: the bot makes a private voice channel, moves everyone in voice into "
                        "it, and deletes it once everyone has left. You must be in voice first."),
    ]),
    ("Moderators (Manage Server or the Popaco Bot Moderator role)", [
        ("hunted", "The enemy list: add/remove players or whole guilds (paste up to 100), tag players, look "
                   "someone up, choose whether enemy deaths and levels are shown."),
        ("allies", "The same for allies."),
    ]),
    ("Admins (Manage Server)", [
        ("init", "Start tracking a world: creates its channels and ping roles. Safe to run again after an error."),
        ("repair", "Recreate a world's deleted channels or roles, and the role buttons."),
        ("remove", "Stop tracking a world and delete everything `/init` made for it."),
        ("settings", "Fullbless level, exiva lists, level filters for channels and the online list, neutrals, "
                     "mass log alerts, the command log channel, and the member role (only that role sees my channels "
                     "and private hunts)."),
        ("clear", "Empty a world's deaths and/or levels channel (asks first)."),
    ]),
]

CHANNELS = (
    "📈 **online**: allies and enemies online, ⚡ fresh logins; the channel name shows 🤍 allies and 💀 enemies.\n"
    "💀 **deaths**: ally/enemy deaths within seconds, pings, exiva lines, mass log alerts.\n"
    "💖 **levels**: level-ups.  📊 **statistics**: bosses due, after server save.\n"
    "👑 **notifications**: buttons to get the Fullbless, Rare Boss, PVP and Masslog ping roles.\n"
    "📡 **status**: how often allies and enemies are really checked, and how fast deaths get posted."
)


def guide_embed() -> discord.Embed:
    embed = discord.Embed(title="Popaco Bot commands", color=embeds.BRAND_COLOR)
    for heading, entries in SECTIONS:
        embed.add_field(name=heading, inline=False,
                        value="\n".join(f"`/{name}`: {text}" for name, text in entries))
    embed.add_field(name="Channels", value=CHANNELS, inline=False)
    return embed


COMMANDS_CHANNEL = "📖・ᴄᴏᴍᴍᴀɴᴅs"


def same_channel_name(stored: str, wanted: str) -> bool:
    """Discord stores text-channel names with spaces turned into hyphens."""
    return stored == wanted.replace(" ", "-") or stored == wanted


async def ensure_readonly_channel(guild: discord.Guild, category: discord.CategoryChannel,
                                  name: str) -> discord.TextChannel:
    """A channel in the bot's category that everyone may read and only the bot posts in."""
    channel = next((c for c in category.text_channels if same_channel_name(c.name, name)), None)
    if channel is None:
        channel = await guild.create_text_channel(name, category=category, overwrites={
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True,
                                                  read_message_history=True),
            guild.default_role: discord.PermissionOverwrite(send_messages=False, create_public_threads=False),
        })
    return channel


async def upsert_message(channel: discord.TextChannel, embed: discord.Embed) -> None:
    """Keep the bot's one message in `channel` showing `embed`: post it, or edit it when it changed."""
    mine = [m async for m in channel.history(limit=20) if m.author.id == channel.guild.me.id]
    if not mine:
        await channel.send(embed=embed)
    elif not (mine[0].embeds and mine[0].embeds[0].to_dict() == embed.to_dict()):
        await mine[0].edit(embed=embed)


async def ensure_guide(guild: discord.Guild, category: discord.CategoryChannel) -> discord.TextChannel:
    """The read-only commands channel in `category`, with the guide as its one message."""
    channel = await ensure_readonly_channel(guild, category, COMMANDS_CHANNEL)
    await upsert_message(channel, guide_embed())
    return channel
