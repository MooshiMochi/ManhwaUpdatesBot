# ManhwaUpdatesBot v2

A thin Discord bot that delegates all manga scraping, search, chapter listing, tracking, and update detection to a separate crawler service. The bot keeps Discord-facing state locally: bookmarks, per-guild tracking, user subscriptions, guild settings, premium grants, and notification offsets.

> **v1 users:** the original bot with in-bot scraping and the 25-minute polling cog is archived on the [`v1`](https://github.com/MooshiMochi/ManhwaUpdatesBot/tree/v1) branch. v2 is a clean rewrite with no shared runtime code.

## What changed

- **Push, not poll.** New chapters arrive from the crawler over `notification_event` WebSocket pushes.
- **No in-bot scraping.** The bot does not ship cloudscraper, captcha logic, or scanlator HTML parsers.
- **Disconnect-safe catch-up.** The persisted notification offset lets the bot replay missed events after restarts.
- **Refcounted tracking.** One crawler `track_series` call covers every guild that tracks the same series.
- **Three-source premium.** Manual DB grants, Patreon active patrons, and Discord App Subscription entitlements can all unlock premium gates.
- **Same user-facing commands.** Slash command names, core parameters, embeds, and pagination behavior are preserved from v1.

## Requirements

- Python 3.14.2
- A running crawler service with a WebSocket API key
- A Discord application and bot token
- Discord **members** privileged intent enabled
- Optional: Discord premium SKUs for App Subscriptions
- Optional: Patreon OAuth token and campaign ID for Patreon-based premium

Message content and presences intents are intentionally not used. Owner dev commands are invoked by mentioning the bot, for example `@ManhwaUpdatesBot d sync`.

## Quick start

```bash
gh repo clone MooshiMochi/ManhwaUpdatesBot
cd ManhwaUpdatesBot
python -m venv .venv
. .venv/Scripts/activate      # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e .[dev]

cp .env.example .env
cp config.example.toml config.toml
# Fill DISCORD_BOT_TOKEN, CRAWLER_API_KEY, crawler URLs, owner_ids, and optional premium settings.

python main.py
```

The crawler must be running before the bot can answer crawler-backed commands such as `/search`, `/info`, `/chapters`, `/track new`, and `/supported_websites`.

## Configuration walkthrough

Secrets live in `.env`, which is gitignored:

```env
DISCORD_BOT_TOKEN=...
CRAWLER_API_KEY=...
PATREON_ACCESS_TOKEN=...
```

Non-secret deployment settings live in `config.toml`, copied from [`config.example.toml`](config.example.toml):

- `[bot]`: owner Discord IDs, log level, optional dev guild guard.
- `[crawler]`: WebSocket URL, REST base URL, request timeout, reconnect tuning, consumer key.
- `[db]`: SQLite database path.
- `[premium]`: premium enablement and owner bypass.
- `[premium.discord]`: Discord user and guild SKU IDs plus upgrade URL.
- `[premium.patreon]`: Patreon campaign ID, polling interval, freshness window, tier filters, pledge URL.
- `[notifications]`: guild and DM fan-out concurrency.
- `[supported_websites_cache]`: cache TTL for `/supported_websites`.

For premium setup details, see [`docs/premium.md`](docs/premium.md). For service deployment, backups, and upgrades, see [`docs/deployment.md`](docs/deployment.md). For nginx or Caddy notes, see [`docs/reverse-proxy.md`](docs/reverse-proxy.md).

## Architecture

```text
Discord ──────► ManhwaUpdatesBot (this repo)
                  │
                  │   WebSocket /ws
                  │   request/response: search, info, chapters, track_series, ...
                  │   push: notification_event
                  ▼
                Crawler service (crawler_backend)
```

The bot owns:

- Bookmarks, folders, and last-read chapter state.
- Per-guild tracked series and ping roles.
- User subscriptions for DM notifications.
- Guild settings such as notification channel and paid-chapter toggle.
- Premium grants and Patreon link cache.
- Notification consumer offset for replay/ack.

The crawler owns:

- Site schemas and scraping.
- Search, info, and chapter retrieval.
- Scheduled update checks.
- New-chapter notification persistence and WebSocket push delivery.

## Development

```bash
python -m ruff format .
python -m ruff check .
python -m pytest
```

Use conventional commit messages where practical, for example `Add docs, Dockerfile, and CI workflow`. Implementation plans are kept in [`plans/`](plans/) so future phases can be audited against the original migration roadmap.

## Docker

A minimal image is provided for deployments that prefer containers:

```bash
docker build -t manhwa-bot .
docker run --rm --env-file .env -v "$PWD/config.toml:/app/config.toml:ro" -v "$PWD/data:/app/data" manhwa-bot
```

Set `[db].path` to a mounted location such as `data/manhwa_bot.db` when running in Docker.

## License

See [`LICENSE`](LICENSE).
