# ManhwaUpdatesBot v2

A thin Discord bot that delegates all manga scraping, search, and update detection to a separate **crawler service**, keeping bookmarks, per-guild tracking, subscriptions, and guild configuration in its own local SQLite database.

> **v1 users:** the original bot (with built-in scraping, scanlator modules, and a 25-minute polling cog) lives on the [`v1`](https://github.com/MooshiMochi/ManhwaUpdatesBot/tree/v1) branch and is unmaintained. Its development branch is [`v1-dev`](https://github.com/MooshiMochi/ManhwaUpdatesBot/tree/v1-dev). v2 (this branch) is a clean rewrite with no shared code.

## What's different from v1

- **Push, not poll.** New chapters arrive over a WebSocket the moment the crawler detects them, instead of every 25 minutes.
- **No in-bot scraping.** The bot speaks only to the crawler service — no cloudscraper, captcha solvers, or per-scanlator modules in this repo.
- **Disconnect-safe.** Persisted notification offset means a restart or network blip never drops chapter events.
- **Three-source premium.** Database-managed grants (with optional expiry / free trials), Patreon active patrons (auto-detected via Discord social-connection link), or Discord App Subscriptions — any one qualifies.
- **Same UX.** All slash commands, embeds, and pagination behavior preserved.

## Requirements

- Python 3.14.2
- A running [crawler service](../crawler_backend) with an issued API key
- A Discord application with the **members** privileged intent enabled (message content and presences are NOT used)
- (Optional) Patreon access token + campaign ID for Patreon-tier premium
- (Optional) Discord premium SKUs configured in the Developer Portal

## Quick start

```bash
# Clone and install
gh repo clone MooshiMochi/ManhwaUpdatesBot
cd ManhwaUpdatesBot
python -m venv .venv
. .venv/Scripts/activate         # Windows: .venv\Scripts\activate
pip install -e .

# Configure
cp .env.example .env
cp config.example.toml config.toml
# edit both — fill in DISCORD_BOT_TOKEN, CRAWLER_API_KEY, etc.

# Run
python main.py
```

## Configuration

Secrets go in `.env` (gitignored). Everything else goes in `config.toml`. See [`.env.example`](.env.example) and [`config.example.toml`](config.example.toml).

## Architecture

```
Discord ──────► ManhwaUpdatesBot (this repo)
                  │
                  │   WebSocket /ws  (search, info, chapters, track_series, ...)
                  │   Push: notification_event
                  ▼
                Crawler service (crawler_backend)
```

The bot owns:
- **Bookmarks** (per user, with folders and last-read chapter)
- **Tracked series per guild** (with refcount across guilds — the bot calls `track_series` on the crawler exactly once per series, no matter how many guilds are interested)
- **User subscriptions** (per series, for DM notifications)
- **Guild settings** (notification channel, default ping role, paid-chapter toggle)
- **Premium grants** (manual issuance with optional expiry)
- **Patreon link cache** (Discord ↔ Patreon user-id mapping, refreshed on a timer)

The crawler owns:
- **Scraping** (browser automation, schemas, anti-bot)
- **Update detection** (scheduled checks, new-chapter discovery)
- **Notification fan-out** (push events to subscribed clients)

## License

See [LICENSE](LICENSE).
