# Backlog

Features to build after the Python port's essential phases (see `python-port-plan.md`).

## 1. Character ownership verification

**Status:** does not exist. The comment field is dropped on parse today
(`tibiadata/response/CharacterResponse.scala` has no `comment`; the fansite API's
`comment` is parsed then discarded in `CharacterMapping`).

**Flow:**
1. `/verify character:<name>` gives the user a short random code (e.g. `VB-7KQ2`), valid 15 minutes, stored against their Discord id.
2. User pastes the code anywhere in that character's comment on tibia.com.
3. User presses **Check**. Bot fetches the character sheet (TibiaData `/v4/character`, which includes `comment`) and looks for the code.
4. On match: store `verified_characters(user_id, character, verified_at)`, then post a report:
   - current guild and rank
   - **traded** flag (the sheet's `traded` field)
   - former names, former worlds
   - account status, creation date, deaths
5. User can remove the code afterwards; verification persists.

**Limitation:** Tibia exposes only the *current* guild. Guild history needs our own
tracking: record every guild we see a verified (or listed) character in over time,
building on `tracked_activity` which already stores current guild per tracked player.
Optionally scrape guildstats.eu for history before our own records exist.

**Uses:** gate respawn claims or role grants to verified characters; prove a
character belongs to a member before adding to allies.

## 2. Enemy kill / death feed

**Status:** partly exists.

What exists today:
- `/hunted` enemy player and guild lists.
- A hunted player's **death** is posted (green, exiva line, optional fullbless ping).
- An **ally killed by players** pings and can auto-add the killers to hunted.

What is missing:
- No alert when a hunted player or hunted-guild member **kills** someone neutral or unlisted. Killer names are plain text, with no icon, no ping and no frag record.
- No dedicated enemy-activity channel; everything mixes into the deaths channel.
- No per-user DM subscriptions for "enemy X died / killed".
- Only characters online on the tracked world are watched.

**Build:**
1. When scanning any death, mark killers that match hunted players/guilds (an enemy icon on the death embed).
2. Record every frag where killer *or* victim is listed (today it's victim only), in `frag_event`.
3. Optional `enemy-activity` channel per world: "**X** (Enemy Guild) killed **Y** [lvl]" and "**X** (Enemy) died to …".
4. Optional role ping / DM subscription per enemy name or guild.
5. Daily PvP summary (`PvpEmbeds`) automatically includes enemy kills once (2) lands.

## 3. Enemy login alerts

**Status:** partly exists.

What exists today:
- The online list marks hunted players who logged in within the last 15 minutes with `:zap:`.
- Mass-log alert: a role ping or DM when *enough* enemies log in at once (`MasslogDetector`, `masslog_notifications`).
- Bounty DM: a per-user DM when one specific watched character logs in (`NotifyService.onBountyLogin`, `bounty_notifications`).

What is missing: a plain "enemy online" alert for any hunted player or hunted-guild member.

**Build:**
1. On each 60s world poll, diff the online roster against the previous one; new names that match hunted players/guilds are "enemy logins".
2. Post to a per-world channel (or the online channel's thread): "**X** (Enemy Guild, 512 EK) logged in".
3. Ping an `<World> Enemy Online` role, with a per-character cooldown (e.g. 30 min) so relogs and disconnects don't spam.
4. Optional level floor and per-guild on/off in `/settings`.
5. Ignore the first poll after a bot restart (everyone looks "new").
