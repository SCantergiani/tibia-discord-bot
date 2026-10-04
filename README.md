# Popaco Bot

A Discord bot for a Tibia guild: deaths and level-ups of your allies and enemies within seconds, who of
them is online, mass-log alerts, rare boss predictions, loot splits and private party channels.

A Python rewrite of [Violent Bot](https://violentbot.xyz) for one group of friends, run on your own
machine with your own copy of TibiaData.

## Features

| Command / channel | What it does |
|---|---|
| `/setup world:` | Creates the world's channels (📈 online, 💀 deaths, 💖 levels, 📊 statistics) and ping roles |
| `/hunted`, `/allies` | Enemy and ally lists: players and whole guilds, tags, bulk paste, auto clean-up of traded/deleted characters |
| 💀 deaths | Every ally/enemy death within ~5–10 s, coloured by side, exiva lines, pings (Fullbless, PVP, Rare Boss), killers of allies auto-added to hunted |
| 💖 levels | Level-ups, batched and silent |
| 📈 online | Only allies and enemies, grouped by guild, ⚡ fresh logins; the channel name carries the counts |
| Mass log | Alert in deaths when many enemies log in at once, ~5 s after tibia.com shows it |
| 📊 statistics, `/bosses` | Which rare bosses are due today, from daily kill statistics |
| `/lootsplit` | Paste the party hunt analyser, get the transfer commands |
| `/privatehunt` | Pick a party: private voice channel, party moved in, gone when empty |
| `/watchdog` | A [TibiaCardinal Watchdog](https://tibiacardinal.com/watchdog) room link for a party |
| `/settings`, `/clear`, `/repair`, `/remove` | Filters and pings, emptying channels, maintenance |

Plan and history: [`docs/python-port-plan.md`](docs/python-port-plan.md). Ideas: [`docs/BACKLOG.md`](docs/BACKLOG.md).

## Run it locally

You need Docker and [uv](https://docs.astral.sh/uv/).

### 1. Create your Discord bot (once)

1. https://discord.com/developers/applications → **New Application**.
2. **Bot** tab → **Reset Token** → copy it: this is `TOKEN`. Keep it secret. Turn **Public Bot** off; leave
   every *Privileged Gateway Intent* off.
3. **OAuth2 → URL Generator**: tick `bot` and `applications.commands`, and the bot permissions
   **Manage Roles, Manage Channels, View Channels, Send Messages, Embed Links, Read Message History,
   Mention Everyone, Connect, Move Members**. Open the URL and add the bot to your server.
4. Discord *User Settings → Advanced → Developer Mode* on; right-click your server → **Copy Server ID**:
   this is `DEV_GUILD_ID` (commands then appear instantly while testing).

### 2. Start it

```bash
cp .env.example .env                                   # fill in TOKEN and DEV_GUILD_ID
docker compose -f docker-compose.dev.yml up -d --wait  # Postgres on :5433, TibiaData on :8081
uv sync
uv run tibiabot
```

Then `/setup world: <your world>` in Discord.

### Why your own TibiaData

The public TibiaData API serves character pages up to 5 minutes old. Your own instance scrapes tibia.com
on every request, so the bot polls every 30 seconds, re-checks allies and enemies every 5 seconds (at
most `FAST_POLL_MAX_PER_SECOND`, default 2, requests to tibia.com), and starts a full poll the moment
tibia.com refreshes its online list (once a minute). Hiding neutral deaths and levels in `/settings`
stops the bot fetching neutral players at all.

## Deploy

Everything runs from one compose file on any machine with Docker:

```bash
cp .env.example .env    # TOKEN, POSTGRES_PASSWORD; leave DEV_GUILD_ID empty for global commands
docker compose up -d --build
docker compose logs -f bot
```

Back up the `pgdata` volume: boss predictions need the kill history it accumulates.

## Tests

```bash
uv run pytest                                                                               # unit tests
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_PASSWORD=devpassword uv run pytest      # + database
```

## License

[PolyForm Noncommercial 1.0.0](LICENSE), inherited from the original project, whose code, data and
artwork this is derived from: free to use and change, **not** for commercial use. Required notice:
Copyright Violent Beams (https://violentbot.xyz).
