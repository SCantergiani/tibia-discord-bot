# Python port plan

Port only what our group uses. The Scala bot stays the reference implementation until
each Python phase matches it.

## Scope

| In | Out (not ported) |
|---|---|
| Death tracking | Patreon / paywall (everything treated as active) |
| Level-up tracking | Highscores, boosted boss/creature, Galthen satchel |
| Online lists | `/status` owner dashboard, `/admin` |
| Loot split | Primary/secondary multi-bot Redis relay |
| Respawn web board backend (frontend `board.html` kept as-is; no Discord forum side) | Fansite API second source |
| Boss predictions (daily statistics post) | Dream Court, world transfers, guild activity channel |
| Supporting: `/setup`, `/repair`, `/hunted`, `/allies`, `/settings` | Mass-log / bounty DMs (maybe later) |

`/hunted` and `/allies` are not optional: death colours, pings, and the online list's
enemy section all depend on them.

## Stack

- Python 3.13, `discord.py` 2.x (slash commands, buttons, modals, forum threads)
- `asyncpg` for Postgres, `aiohttp` for TibiaData and as the dashboard web server
- `redis` (asyncio) optional, same as today
- `pytest` + `pytest-asyncio`; port the Scala specs for each phase as acceptance tests

## Data

Fresh data: no migration from an existing install. Schema is kept identical
(`bot_cache` shared DB plus one `_<guildId>` DB per guild, same tables and columns, see
`persistence/SchemaInitializer.scala` and the `Jdbc*Repository` lazy `ALTER`s), so the
Scala bot can be pointed at the Python bot's database to compare behaviour.
Python consolidates the scattered `ALTER`s into one DDL file per database.

Env vars stay the same (`TOKEN`, `POSTGRES_HOST`, `POSTGRES_PASSWORD`, `TIBIADATA_HOST`,
`REDIS_*`, `SESSION_SECRET`, `DISCORD_CLIENT_SECRET`, `STATUS_DOMAIN`, `BOT_OWNER_ID`,
`RESPAWN_ENABLED`).

## Phases

Each phase ends runnable, with its ported specs green.

| # | Phase | Scala reference | Size (Scala lines) |
|---|---|---|---|
| 0 ✅ | Skeleton: config, DB init, TibiaData client with 300s character age cache, world poll loop, `/setup`, `/repair`, guild/world state | `Config`, `SchemaInitializer`, `tibiadata/*`, `setup/ChannelService`, `state/StreamState` | ~1500 |
| 1 ✅ | Loot split: `/lootsplit`, modal, settlement embed | `lootsplit/*`, `interactions/LootSplit`, `LootSplitEmbeds` | ~520 |
| 2 ✅ | Hunted/allies lists: panels, add/remove/clear, tags, traded/moved/deleted flagging and review sweep | `hunted/*`, `panels/*`, `PanelButtons`, `PanelModals` | ~1500 |
| 3 ✅ | Deaths + levels + `/settings` (the filters it sets): 60s poll, death detection, embeds/colours/pings, frags, screenshot button, auto-hunted, level posts | `TibiaBot.scala` scan/post stages, `Killers`, `DeathEmbeds`, `LevelTracker`, `LevelVisibility` | ~850 |
| 4 | Online lists: roster, grouping, edit-in-place packing, channel/category rename with cooldown | `OnlineTracker`, `OnlineListEmbeds`, `OnlineListState`, `OnlineListGrouping` | ~900 |
| 5 | Boss predictions: daily killstatistics fetch, predictor, statistics post | `statistics/*`, `KillStatisticsSchedule`, `ServerSaveSchedule` | ~600 |
| 6 | Respawn **web board only**: Discord OAuth, all `/dashboard` routes `board.html` calls, claims/queue/bookings/stamina, expiry sweep, sprite cache | `web/DiscordAuth`, `web/RespawnDashboardRoute`, `respawn/RespawnService`, `RespawnCatalogue` | ~3500 |

Phase 6 must keep the JSON contracts `board.html` relies on exactly (routes and shapes
are listed in the porting map); the two unused routes (`/extend`, `/bookings`) are
dropped. The Discord side of respawns (forum threads, pinned board image, claim
buttons, DMs, `/stamina`, `/bookings`) is **not** ported for now; it can be added later
on top of the same service layer.

## Notes from Phase 0

- Custom emojis are uploaded as the bot's own *application emojis* from
  `tibia-bot/src/main/resources/discord emojis/` on startup; the Scala config's emoji ids belong to the
  original author's server and don't render for another bot. Images missing from that folder (progress
  bars, vocation weapons) fall back to Unicode until someone adds them.
- `/setup` no longer creates the activity channel, mass-log/bounty roles, Galthen/boosted posts or the
  respawn forum (not ported); their columns hold `0`.
- Slash commands go to `DEV_GUILD_ID` instantly while testing; unset, they register globally.

- The bot is named **Popaco Bot** (category "Popaco Bot", role "Popaco Bot Moderator"); `/setup` and
  `/repair` rename a server's existing "Violent Bot" category and moderator role in place.
- `/settings` moved from Phase 2 to Phase 3, alongside the death/level/online filters it controls.

- Phase 3 notes: the "Add Screenshot" button on PvP deaths of enemies is not ported (it needs the
  message-content intent; see backlog). Death thumbnails come from TibiaWiki instead of the original
  author's site. On a world's first poll level-ups are remembered but not posted, so a fresh start
  doesn't flood the levels channel. Members opt in to pings with role buttons in the notifications
  channel; `/repair` posts them if missing.

## Security carry-over

The Python version starts with the fixes made on the `security-fixes` branch:
owner from `BOT_OWNER_ID` (no hardcoded id), escaped output in any HTML, permission
re-check on every modal submit, constant-time session HMAC, 32+ char `SESSION_SECRET`,
Redis password required, `Origin` check on dashboard POSTs, CSP headers.
