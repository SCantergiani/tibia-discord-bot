# Tibia bot (Python port)

Port plan and progress: [`../docs/python-port-plan.md`](../docs/python-port-plan.md).
Backlog: [`../docs/BACKLOG.md`](../docs/BACKLOG.md).

## Run it locally

You need Docker (for Postgres) and [uv](https://docs.astral.sh/uv/).

### 1. Create your own Discord bot (once)

1. Open https://discord.com/developers/applications → **New Application**, name it.
2. **Bot** tab → **Reset Token** → copy it. This is `TOKEN`. Keep it secret.
3. Still on the **Bot** tab, leave every *Privileged Gateway Intent* off; the bot doesn't need them.
4. **OAuth2 → URL Generator**: tick `bot` and `applications.commands`, then under bot permissions tick
   **Manage Roles, Manage Channels, View Channels, Send Messages, Embed Links, Read Message History,
   Mention Everyone**. Open the generated URL and add the bot to a test server you own.
5. In Discord: *User Settings → Advanced → Developer Mode* on. Right-click your test server →
   **Copy Server ID**. This is `DEV_GUILD_ID`.

### 2. Start Postgres and the bot

```bash
cd python
cp .env.example .env              # then fill in TOKEN and DEV_GUILD_ID
docker compose -f docker-compose.dev.yml up -d --wait
uv sync
uv run tibiabot
```

On first start the bot creates the `bot_cache` database, uploads its custom emojis to your application
(Developer Portal → your app → **Emojis** shows them), and registers `/setup`, `/repair` and `/remove` in
your test server.

### 3. Try it

- `/setup world: Antica` creates the **Popaco Bot** category (command log and notifications), a
  category for the world with online, deaths, levels and statistics channels, and the
  `Antica Fullbless`, `Antica Rare Boss`, `Antica PVP` and `Popaco Bot Moderator` roles.
- The console then logs one line per minute per tracked world:
  `Antica: 541 online, 541 sheets (541 cached), 3 recently offline`. Posting to the channels comes in
  later phases.
- Delete a channel and run `/repair world: Antica` to get it back.
- `/remove world: Antica` deletes everything `/setup` made.

## Tests

```bash
uv run pytest                                   # unit tests
POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433 POSTGRES_PASSWORD=devpassword uv run pytest   # plus DB tests
```

## Reset everything

```bash
docker compose -f docker-compose.dev.yml down -v   # deletes the local database
```
