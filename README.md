# Manhwa Updates Bot - Discord Bot for Manhwa Chapter Notifications

Manhwa Updates Bot is a hosted Discord bot that tracks manhwa, manga, and manhua chapter updates and sends notifications to your Discord server or DMs.

**No self-hosting required. Invite the hosted bot and use it out of the box.**

[Invite the Hosted Bot](https://discord.com/api/oauth2/authorize?client_id=1031998059447590955&permissions=412854111296&scope=bot%20applications.commands) · [Support Server](https://discord.gg/TYkw8VBZkr) · [Top.gg](https://top.gg/bot/1031998059447590955) · [Discord App Directory](https://discord.com/discovery/applications/1031998059447590955)

## Features

- Automatic manhwa chapter update notifications in Discord.
- Track series in server channels and optionally ping roles when chapters release.
- Subscribe to personal DM alerts for tracked series.
- Bookmark manga/manhwa/manhua and update reading progress.
- Browse supported manhwa and manga websites with `/supported_websites`.
- Search titles, view series info, and list chapters with slash commands.
- Hosted public bot for communities, reading groups, and scanlation-style update tracking.

## Quick Start for Discord Servers

1. [Invite the hosted bot](https://discord.com/api/oauth2/authorize?client_id=1031998059447590955&permissions=412854111296&scope=bot%20applications.commands).
2. Run `/help` to see the main commands.
3. Run `/settings` to choose your server notification channel.
4. Run `/track new` to track a manhwa, manga, or manhua series.
5. Use `/supported_websites` to see which sources are currently available.

## Common Commands

| Command | What it does |
| --- | --- |
| `/track new` | Track a series in a server channel and optionally ping a role. |
| `/track list` | View all series tracked by the server. |
| `/subscribe new` | Subscribe to personal DM chapter notifications. |
| `/bookmark new` | Save a series and track your reading progress. |
| `/search` | Search for a series by title. |
| `/info` | Show series metadata and links. |
| `/chapters` | List available chapters. |
| `/supported_websites` | Browse supported manhwa/manga websites. |
| `/stats` | View public bot stats. |
| `/help` | Get started with the bot. |

## Who is it for?

Manhwa Updates Bot is built for Discord communities that want automatic chapter notifications without manually checking websites. It is useful for:

- Manhwa servers and reading groups.
- Manga/manhua communities that follow multiple sources.
- Server owners who want update channels and role pings.
- Readers who want DM notifications and bookmarks.
- Users who need direct website tracking instead of only MangaDex/RSS-based alerts.

## Supported Websites

Supported websites are provided by the crawler service and can change over time. In Discord, run:

```text
/supported_websites
```

The bot is designed for manhwa, manga, and manhua chapter update tracking from supported websites, including scanlator-style sources when available.

## FAQ

### Is Manhwa Updates Bot hosted?

Yes. **No self-hosting is required.** The public hosted Discord bot can be invited and used out of the box.

### Is this a manhwa Discord bot?

Yes. Manhwa Updates Bot is a Discord bot for manhwa chapter notifications, server tracking, role pings, DM subscriptions, bookmarks, and supported-website browsing.

### Does it only support manhwa?

No. The bot is focused on manhwa update tracking, but it can also track manga and manhua from supported websites.

### Is this a manwha updates bot?

Yes — if you searched for "manwha updates bot," you probably mean "manhwa updates bot." Manhwa Updates Bot tracks manhwa chapter releases and sends Discord notifications.

### Can I self-host it?

This repository contains the bot source code for development and self-hosted deployments, but normal users should use the hosted invite above.

## Self-hosting / Developer Setup

A thin Discord bot delegates all manga scraping, search, chapter listing, tracking, and update detection to a separate crawler service. The bot keeps Discord-facing state locally: bookmarks, per-guild tracking, user subscriptions, guild settings, premium grants, and notification offsets.

> **v1 users:** the original bot with in-bot scraping and the 25-minute polling cog is archived on the [`v1`](https://github.com/MooshiMochi/ManhwaUpdatesBot/tree/v1) branch. v2 is a clean rewrite with no shared runtime code.

### What changed in v2

- **Push, not poll.** New chapters arrive from the crawler over `notification_event` WebSocket pushes.
- **No in-bot scraping.** The bot does not ship cloudscraper, captcha logic, or scanlator HTML parsers.
- **Disconnect-safe catch-up.** The persisted notification offset lets the bot replay missed events after restarts.
- **Refcounted tracking.** One crawler `track_series` call covers every guild that tracks the same series.
- **Three-source premium.** Manual DB grants, Patreon active patrons, and Discord App Subscription entitlements can all unlock premium gates.
- **Same user-facing commands.** Slash command names, core parameters, embeds, and pagination behavior are preserved from v1.

### Requirements

- Python 3.14.2
- A running crawler service with a WebSocket API key
- A Discord application and bot token
- Discord **members** privileged intent enabled
- Optional: Discord premium SKUs for App Subscriptions
- Optional: Patreon OAuth token and campaign ID for Patreon-based premium

Message content and presences intents are intentionally not used. Owner dev commands are invoked by mentioning the bot, for example `@ManhwaUpdatesBot d sync`.

### Local quick start

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

## Running from a git worktree

If you've created a worktree (e.g. `.worktrees/my-feature`) to work on a feature branch in isolation, **always invoke that worktree's own venv** when starting the bot:

```powershell
cd "<path-to-worktree>"
.\.venv\Scripts\python.exe main.py
```

Each worktree has its own `.venv` with `manhwa_bot` installed editable from that worktree's `src/`. Running the worktree's `main.py` with the **main** repo's venv loads two copies of `manhwa_bot` into `sys.modules` (the main src via the editable install, and the worktree src via cwd on sys.path), which silently breaks `isinstance` checks on `CrawlerError` and other classes — `except CrawlerError` in a cog fails to catch errors raised by the client.

To set up a fresh worktree's venv:

```powershell
cd "<path-to-worktree>"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## Configuration walkthrough

Secrets live in `.env`, which is gitignored:

```env
DISCORD_BOT_TOKEN=...
CRAWLER_API_KEY=...
PATREON_ACCESS_TOKEN=...
```

Non-secret deployment settings live in `config.toml`, copied from [`config.example.toml`](config.example.toml):

- `[bot]`: owner Discord IDs, log level, owner command prefix, optional dev guild guard.
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
