# Build plans for ManhwaUpdatesBot v2

Each file in this directory is a self-contained spec for one phase of v2.
Hand the file path to a fresh Claude Code session along with the trigger
phrase ("build the DB layer", "build the catalog cog", etc.) and the agent
has everything it needs.

## Master plan

The full architectural plan lives outside the repo at:

```
C:\Users\rchir\.claude\plans\https-github-com-mooshimochi-manhwaupdat-luminous-treehouse.md
```

Every phase plan in this directory is a slice of that master plan and
references it for cross-cutting context (envelope shape, intents, premium
sources, refcount semantics, etc.).

## Order

| # | Phase | File | Status |
|---|---|---|---|
| 1 | Repo flip + scaffolding | (done) | ✅ in commits 5858f22, 47746bb |
| 2 | Config + crawler client | (done) | ✅ in commit 47746bb |
| 3 | DB layer | [phase-03-db-layer.md](phase-03-db-layer.md) | pending |
| 4 | Bot skeleton | [phase-04-bot-skeleton.md](phase-04-bot-skeleton.md) | pending |
| 5 | Premium subsystem | [phase-05-premium.md](phase-05-premium.md) | pending |
| 6 | Catalog cog | [phase-06-catalog-cog.md](phase-06-catalog-cog.md) | pending |
| 7 | Tracking cog | [phase-07-tracking-cog.md](phase-07-tracking-cog.md) | pending |
| 8 | Subscriptions cog | [phase-08-subscriptions-cog.md](phase-08-subscriptions-cog.md) | pending |
| 9 | Bookmarks cog | [phase-09-bookmarks-cog.md](phase-09-bookmarks-cog.md) | pending |
| 10 | Settings cog | [phase-10-settings-cog.md](phase-10-settings-cog.md) | pending |
| 11 | Updates cog | [phase-11-updates-cog.md](phase-11-updates-cog.md) | pending |
| 12 | General cog | [phase-12-general-cog.md](phase-12-general-cog.md) | pending |
| 13 | Dev cog | [phase-13-dev-cog.md](phase-13-dev-cog.md) | pending |
| 14 | Docs + CI | [phase-14-docs-and-ci.md](phase-14-docs-and-ci.md) | pending |
| 15 | Verification | [phase-15-verification.md](phase-15-verification.md) | pending |

Phases 3, 4, 5 must run in order (cogs depend on bot skeleton; cogs also
depend on the DB and premium services). Phases 6–13 are mostly independent
once 3–5 are done — see each file's "Depends on" section.

## How to invoke

In a new Claude Code session, paste:

> Build phase N. The plan file is `plans/phase-NN-<name>.md`. The master
> plan is at `~/.claude/plans/https-github-com-mooshimochi-manhwaupdat-luminous-treehouse.md`.
> Read both, then implement.

Each plan also names the recommended Claude model and reasoning effort at
the top.
