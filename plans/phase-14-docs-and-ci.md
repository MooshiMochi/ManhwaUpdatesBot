# Phase 14 — README, deployment notes, optional Dockerfile, CI workflow

> **Recommended model:** Claude **Haiku 4.5** at **low** reasoning effort.
> Documentation + a 30-line YAML. Haiku is plenty.

## Goal

Polish the repo for external use: deployment guide, optional containerization,
CI on push.

## Files

```
README.md                            # expand the existing scaffolded README
docs/
├── deployment.md
├── premium.md                       # how to wire SKUs + Patreon
└── reverse-proxy.md                 # optional: behind nginx/caddy notes
Dockerfile                           # multi-stage Python 3.14 image
.dockerignore
.github/workflows/
├── ci.yml                           # ruff + pytest on push/PR
└── stale.yml                        # optional: auto-close stale issues
```

## Module specs

### `README.md` — expand

The current scaffolded README already explains the architecture. Add:

- **Quick start** (already there).
- **Configuration walkthrough** — link to `docs/premium.md` for the
  premium setup.
- **Deployment** — link to `docs/deployment.md`.
- **Architecture diagram** — keep the existing ASCII one.
- **Contributing** — short section: ruff format, pytest, conventional
  commits, link to plans/ directory.
- **License** — link to LICENSE.

### `docs/deployment.md`

Cover:

1. **systemd unit example** for Linux, with `WorkingDirectory`,
   `EnvironmentFile=.env`, `Restart=always`.
2. **PM2 example** for Node-style deployments.
3. **Windows service** via `nssm` (relevant since the user is on Windows).
4. **Logs**: stdout by default; redirect via systemd or use a file
   handler.
5. **Backup**: just back up `manhwa_bot.db` (SQLite WAL — see
   `wal_checkpoint(TRUNCATE)` before snapshotting).
6. **Upgrades**: `git pull && pip install -e . && systemctl restart
   manhwa-bot`.

### `docs/premium.md`

1. Setting up Discord SKUs in the Developer Portal (link to current docs).
2. Filling `[premium.discord]` in `config.toml`.
3. Patreon: creating an OAuth client, getting the access token, finding
   the campaign id, populating `.env` + `[premium.patreon]`.
4. Manual grants via `@bot d premium grant ...`.
5. Free trials: `@bot d premium grant user 123 30d "trial"`.
6. Auditing: `@bot d premium list` and `@bot d premium check`.

### `Dockerfile`

```dockerfile
FROM python:3.14-slim AS base
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM python:3.14-slim
WORKDIR /app
COPY --from=base /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=base /app /app
COPY main.py ./
ENV PYTHONUNBUFFERED=1
USER 1000:1000
CMD ["python", "main.py"]
```

`.dockerignore`: `.git`, `.venv`, `__pycache__`, `tests`, `*.db`, `.env`,
`docs`, `plans`.

### `.github/workflows/ci.yml`

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.14"
      - run: pip install -e .[dev]
      - run: python -m ruff check .
      - run: python -m ruff format --check .
      - run: python -m pytest -v
```

## Verification

```bash
python -m ruff format docs README.md     # ruff doesn't lint .md but format is harmless
docker build -t manhwa-bot .             # if Docker available locally
gh workflow view ci.yml                  # after first push
```

## Commit message

```
Add docs, Dockerfile, and CI workflow

Deployment guide (systemd / PM2 / Windows service / nssm), premium setup
walkthrough (Discord SKUs + Patreon + manual grants), multi-stage
Dockerfile with non-root user, GitHub Actions CI running ruff + pytest
on push and PR.
```
