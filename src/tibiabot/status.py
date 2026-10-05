"""The 📡 status channel: what the bot is measuring right now, so everyone knows what
to expect (enemies are re-checked faster than allies, how soon deaths show up)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord

from tibiabot import embeds

if TYPE_CHECKING:
    from tibiabot.bot import TibiaBot

STATUS_CHANNEL = "📡・sᴛᴀᴛᴜs"


def _seconds(value: float) -> str:
    return f"{value:.0f}s" if value < 90 else f"{value / 60:.1f} min"


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 1440}d {minutes // 60 % 24}h" if minutes >= 1440 else f"{minutes // 60}h {minutes % 60}m"


def status_embed(bot: TibiaBot, guild_id: int) -> discord.Embed:
    lists = bot.lists.of(guild_id)
    enemies, allies = lists.side_names(True), lists.side_names(False) - lists.side_names(True)
    lines = []
    for world in sorted(bot.state.guild(guild_id).worlds):
        online = {name.lower() for name in getattr(bot.online.get(world), "players", {})}
        poller = bot.pollers.get(world)
        parts = [f"💀 **{len(online & enemies)}** enemies · 🤍 **{len(online & allies)}** allies online"]
        if poller and poller.phase is not None:
            parts.append(f"online list refreshes at **:{poller.phase:02.0f}** each minute")
        if poller and poller.last_poll:
            parts.append(f"last poll <t:{int(poller.last_poll)}:R>")
        lines.append(f"**{world}**: " + " · ".join(parts))
    embed = discord.Embed(title="📡 Popaco Bot status", color=embeds.BRAND_COLOR,
                          description="\n".join(lines) or "*No worlds tracked yet: run `/init`.*")

    stats, rate = bot.stats, bot.rate
    if rate is not None:
        checks = []
        for side, label, target in (("enemy", "Enemies", bot.settings.fast_poll_seconds),
                                    ("ally", "Allies", bot.settings.ally_poll_seconds)):
            every = stats.check_every(side)
            checks.append(f"{label}: every **~{_seconds(every)}**" if every is not None
                          else f"{label}: none online (target every {target:g}s)")
        embed.add_field(name="How often online allies/enemies are re-checked (last 10 min)", inline=False,
                        value=" · ".join(checks) + "\nEnemies always go first; anyone who just logged out "
                                                   "(dying logs you out) jumps the queue. Allies listed only "
                                                   "through their guild aren't fast-checked: their deaths come "
                                                   "from the public API, up to ~5 minutes late.")
    else:
        embed.add_field(name="Checks", inline=False,
                        value="Public TibiaData API: character pages can be up to 5 minutes old.")

    delays = []
    for side, label in (("enemy", "Enemies"), ("ally", "Allies"), ("neutral", "Others")):
        found = stats.death_delay(side)
        if found:
            delays.append(f"{label}: **~{_seconds(found[0])}** ({found[1]} deaths)")
    embed.add_field(name="Deaths posted after they happen (last 24 h)", inline=False,
                    value=" · ".join(delays) if delays else "*No deaths seen yet.*")

    if rate is not None:
        pushback = (f"last pushback <t:{int(rate.last_pushback)}:R>" if rate.last_pushback
                    else "no pushback since start")
        embed.add_field(name="tibia.com request rate", inline=False,
                        value=f"**{rate.rate:g}/s** now, adapting between {rate.floor:g} and {rate.ceiling:g}/s "
                              f"to how tibia.com answers · {pushback}" + (" · **paused**" if rate.paused else ""))
    embed.set_footer(text=f"Updated every minute · up {_duration(time.time() - stats.started)}")
    return embed
