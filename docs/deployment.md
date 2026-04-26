# Deployment

ManhwaUpdatesBot is a single Python process. It logs to stdout by default, stores runtime state in SQLite, and expects the crawler service to be reachable over WebSocket.

## Linux with systemd

Create a dedicated user and install the app in a fixed directory such as `/opt/manhwa-bot`.

```ini
[Unit]
Description=ManhwaUpdatesBot v2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=manhwa-bot
Group=manhwa-bot
WorkingDirectory=/opt/manhwa-bot
EnvironmentFile=/opt/manhwa-bot/.env
ExecStart=/opt/manhwa-bot/.venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Install and start:

```bash
sudo cp manhwa-bot.service /etc/systemd/system/manhwa-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now manhwa-bot
journalctl -u manhwa-bot -f
```

## PM2

PM2 can supervise Python processes if your host already uses Node-style process management.

```bash
pm2 start main.py --name manhwa-bot --interpreter .venv/bin/python
pm2 save
pm2 logs manhwa-bot
```

On Windows, use the venv interpreter path instead:

```powershell
pm2 start main.py --name manhwa-bot --interpreter .\.venv\Scripts\python.exe
```

## Windows service with NSSM

[NSSM](https://nssm.cc/) is a practical wrapper for running the bot as a Windows service.

```powershell
nssm install ManhwaUpdatesBot "C:\path\to\ManhwaUpdatesBot\.venv\Scripts\python.exe" "main.py"
nssm set ManhwaUpdatesBot AppDirectory "C:\path\to\ManhwaUpdatesBot"
nssm set ManhwaUpdatesBot AppEnvironmentExtra DISCORD_BOT_TOKEN=... CRAWLER_API_KEY=...
nssm set ManhwaUpdatesBot AppStdout "C:\path\to\ManhwaUpdatesBot\logs\stdout.log"
nssm set ManhwaUpdatesBot AppStderr "C:\path\to\ManhwaUpdatesBot\logs\stderr.log"
nssm set ManhwaUpdatesBot Start SERVICE_AUTO_START
nssm start ManhwaUpdatesBot
```

Prefer an `.env` file in the app directory for secrets. Use `AppEnvironmentExtra` only when the host's service management requires environment variables to be injected externally.

## Logs

The bot writes structured logs to stdout/stderr. Let the supervisor capture logs:

- systemd: `journalctl -u manhwa-bot`.
- PM2: `pm2 logs manhwa-bot`.
- NSSM: configure `AppStdout` and `AppStderr` as shown above.

If you add a file handler later, keep stdout enabled so container and service logs still work.

## Backups

The only required persistent bot data is the SQLite database configured by `[db].path`, usually `manhwa_bot.db`.

For a consistent hot backup when WAL mode is active:

```bash
sqlite3 manhwa_bot.db "PRAGMA wal_checkpoint(TRUNCATE);"
cp manhwa_bot.db backups/manhwa_bot.$(date +%F-%H%M%S).db
```

If you cannot run a checkpoint first, back up the `manhwa_bot.db`, `manhwa_bot.db-wal`, and `manhwa_bot.db-shm` files together.

## Upgrades

```bash
git pull
python -m pip install -e .
python -m ruff check .
python -m pytest
sudo systemctl restart manhwa-bot
```

Migrations run on startup. Keep a database backup before pulling large changes or changing Python versions.

## Operational checks

After deployment or upgrade:

- Confirm the bot is online in Discord.
- Run `/supported_websites` to verify crawler connectivity.
- Run `/stats` to verify the local database opens.
- As an owner, run `@ManhwaUpdatesBot d crawler health` to verify crawler diagnostics.
