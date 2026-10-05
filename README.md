# Popaco Bot

A Discord bot for a Tibia guild: deaths and level-ups of your allies and enemies within seconds, who of
them is online, mass-log alerts, rare boss predictions, loot splits and private party channels.

A Python rewrite of [Violent Bot](https://violentbot.xyz) for one group of friends, run on your own
machine with your own copy of TibiaData.

## Features

| Command / channel | What it does |
|---|---|
| `/init world:` | Creates the world's channels (🤍 allies, ⚔️ enemies, 💀 deaths, 💖 levels, 📊 statistics) and ping roles |
| `/hunted`, `/allies` | Enemy and ally lists: players and whole guilds, tags, bulk paste, auto clean-up of traded/deleted characters |
| 💀 deaths | Every ally/enemy death within ~5–10 s, coloured by side, exiva lines, pings (Fullbless, PVP, Rare Boss) |
| 💖 levels | Level-ups, batched and silent |
| 🤍 allies, ⚔️ enemies | Who of them is online, grouped by guild, ⚡ fresh enemy logins; each channel's name carries its count |
| Mass log | Alert in ⚔️ enemies when 5+ enemies log in within 5 minutes, as soon as tibia.com shows it (`MASSLOG_*` in `.env`) |
| 📊 statistics, `/bosses` | Which rare bosses are due today, from daily kill statistics |
| `/split` | Paste the party hunt analyser, get the transfer commands |
| `/privateroom` | Pick a party: private voice channel, party moved in, gone when empty |
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
   this is `DEV_GUILD_ID`: commands then appear instantly, but **only in that server**. Leave it empty
   once the bot is in more than one server (commands then register everywhere; first time can take up
   to an hour).

### 2. Start it

```bash
cp .env.example .env    # fill in TOKEN (and DEV_GUILD_ID while testing)
make                    # starts Postgres (:5433) and TibiaData (:8081) if needed, then the bot
```

`make help` lists the rest: `make test`, `make down`, `make logs`, `make deploy`.

Then `/init world: <your world>` in Discord.

### Why your own TibiaData

The public TibiaData API serves character pages up to 5 minutes old. Your own instance scrapes tibia.com
on every request, so the bot re-checks online enemies every 5 seconds and allies listed by name every 10
(enemies first when the rate can't cover everyone; allies listed only through their guild go through
the public API instead, so a big allied guild costs nothing), and starts a full poll
the moment tibia.com refreshes its online list (once a minute). The request rate to tibia.com adapts:
it starts at 2/s, climbs slowly while tibia.com answers cleanly, up to `FAST_POLL_CEILING` (4), and
halves the moment it pushes back (403/429), one rate for every world since tibia.com counts per IP. Everything that needn't be fresh (guild
rosters, kill statistics, sheets for new list entries and killers) comes from the public API instead
(`TIBIADATA_BULK_HOST`), so it doesn't count against that rate. Hiding neutral deaths and levels in `/settings`
stops the bot fetching neutral players at all.

## Deploy

Everything runs from one compose file on any machine with Docker:

```bash
cp .env.example .env    # TOKEN, POSTGRES_PASSWORD; leave DEV_GUILD_ID empty for global commands
make deploy             # docker compose up -d --build, then follows the bot's logs
```

Back up the `pgdata` volume: boss predictions need the kill history it accumulates.

**Small machines.** The stack uses about 300 MB of RAM (Postgres is tuned for a 1 GB machine in
`docker-compose.yml`); on a 1 GB VM add a swap file so a spike can't kill Postgres:

```bash
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**Outbound traffic** is set almost entirely by the fast-check rate: about 3.6 GB a month per
request/second (each tibia.com page is ~50 KB even compressed, and receiving it costs ~1.4 KB of
acknowledgements). At a steady 2/s that's ~7 GB/month (only reached with 10+ allies/enemies online all the time; lower
`FAST_POLL_CEILING` to bound it); a ceiling of 0.25 fits a 1 GB free allowance, with deaths of
online allies/enemies then caught within about a minute (dying logs you out) rather than seconds.

## Tests

```bash
make test        # unit + database tests (starts the dev Postgres if needed)
uv run pytest    # unit tests only
```

## License

[PolyForm Noncommercial 1.0.0](LICENSE), inherited from the original project, whose code, data and
artwork this is derived from: free to use and change, **not** for commercial use. Required notice:
Copyright Violent Beams (https://violentbot.xyz).
