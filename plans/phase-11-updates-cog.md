# Phase 11 — Updates cog (notification_event consumer + dispatch + ack + catch-up)

> **Recommended model:** Claude **Opus 4.7** at **high** reasoning effort.
> The most architecturally important phase. Catch-up ordering, ack
> semantics, queue-while-replaying, and per-guild fan-out failure
> isolation all need careful reasoning. Worth Opus's stronger ordering
> guarantees in concurrent code. Demote to Sonnet for follow-up tweaks
> after the first version lands.

## Goal

Replace v1's 25-minute polling cog with a push-driven consumer. Receives
`notification_event` from the crawler, fans out to each interested guild's
notification channel and DMs subscribed users, then acks. Handles
disconnect-and-replay so events are never dropped.

## Depends on

- Phase 2 (`crawler/client.py` push handler registry)
- Phase 3 (`db/tracked.py`, `db/subscriptions.py`, `db/guild_settings.py`,
  `db/dm_settings.py`, `db/consumer_state.py`)
- Phase 4 (bot skeleton, with `bot.crawler` available)
- Phase 6 (`formatting.py` for the chapter-update embed)
- Crawler ops: `notifications_list`, `notifications_ack` (master plan refs).

## Files

```
src/manhwa_bot/cogs/updates.py
src/manhwa_bot/crawler/notifications.py
src/manhwa_bot/formatting.py     # extend with chapter_update_embed()
tests/
├── test_notification_consumer.py
└── test_notification_dispatch.py
```

Append `"manhwa_bot.cogs.updates"` to `COGS`.

## Architecture

```
Crawler ──(WS push: notification_event)──► CrawlerClient.on_push handler
                                              │
                                              ▼
                                       NotificationConsumer
                                              │
                                              │  ① queue if catch-up in progress
                                              │  ② dispatch when live
                                              ▼
                                        UpdatesCog.dispatch
                                              │
                                              ├──► guild channels (fanout, bounded concurrency)
                                              └──► DM subscribers (fanout, bounded concurrency)
                                              │
                                              ▼
                                  ConsumerStateStore.set_last_acked
                                              │
                                              ▼
                                   crawler.request("notifications_ack", ...)
```

## Module specs

### `crawler/notifications.py` — `NotificationConsumer`

Lives next to the crawler client (not in `cogs/`) because it manages the
catch-up state machine that's WS-level, not Discord-level.

```python
class NotificationConsumer:
    def __init__(self, *, client: CrawlerClient, store: ConsumerStateStore,
                 consumer_key: str, dispatch: Callable[[NotificationRecord], Awaitable[None]]):
        ...

    async def start(self) -> None
    async def stop(self) -> None
```

State:
- `catching_up: bool` — True between `start()` (or reconnect) and the
  moment the catch-up replay completes. Live pushes that arrive during
  catch-up go into a deque; once catch-up finishes, the deque is drained
  *in order*, then live pushes pass through directly.
- `last_acked: int` — loaded from `consumer_state` on start; advanced
  after every successful dispatch.

Lifecycle:
1. On `start()`: register `client.on_push("notification_event", self._on_push)`.
   Register `client.on_connect(self._on_connect)`.
2. `_on_connect` (called whenever WS connects, including first time and
   every reconnect): set `catching_up=True`, then loop:
   - Call `data = await client.request("notifications_list", consumer_key=..., since_id=last_acked, limit=200)`.
   - Process each record in `data["notifications"]` via `dispatch`,
     advancing `last_acked` after each successful Discord delivery.
   - Call `client.request("notifications_ack", consumer_key=..., last_notification_id=last_acked)`.
   - If `len(records) == 200`, loop again (more pending). Else break.
   - After break: drain queued live pushes (deque) in arrival order. Set
     `catching_up=False`.
3. `_on_push(payload)`:
   - Extract `payload["data"]["notification"]`.
   - If `catching_up`: append to deque (don't dispatch yet — would race
     with catch-up).
   - Else: `await dispatch(record)`. On success advance `last_acked` and
     ack via `notifications_ack`.

Concurrency: a single `asyncio.Lock` serializes the catch-up vs. live
push handoff so no event is processed twice or out of order.

Failure handling:
- If `dispatch` raises, do NOT advance `last_acked` and do NOT ack. The
  next reconnect (or a periodic retry every N minutes) will re-fetch from
  `notifications_list`. This means transient Discord outages cause replays,
  not lost events. The trade-off: a permanently-failing dispatch (e.g.
  guild kicked the bot, channel deleted) blocks all subsequent acks. The
  cog handles this by treating those as success-with-warning (see below).

### `cogs/updates.py` — `UpdatesCog`

Owns the dispatcher. No commands — pure listener cog.

```python
class UpdatesCog(commands.Cog):
    bot: ManhwaBot
    consumer: NotificationConsumer

    async def cog_load(self):
        self.consumer = NotificationConsumer(
            client=self.bot.crawler,
            store=self.bot.consumer_state,
            consumer_key=self.bot.config.crawler.consumer_key,
            dispatch=self.dispatch,
        )
        await self.consumer.start()

    async def cog_unload(self):
        await self.consumer.stop()

    async def dispatch(self, record: NotificationRecord) -> None:
        ...
```

`dispatch(record)`:
1. Extract `(website_key, url_name, payload)` from the record.
2. Build the chapter-update embed via
   `formatting.chapter_update_embed(payload)`.
3. Look up `guilds = await bot.tracked.list_guilds_tracking(website_key, url_name)`.
4. Concurrent fan-out (bounded by `config.notifications.fanout_concurrency`):
   - For each guild row:
     - Load `guild_settings`.
     - Resolve channel: `guild_scanlator_channels` override if present
       for this `website_key`, else `guild_settings.notifications_channel_id`.
       If neither set, skip (warn once).
     - If `payload.chapter.is_premium` is True and
       `guild_settings.paid_chapter_notifs == 0` and
       `config.notifications.respect_paid_chapter_setting` is True, skip.
     - Build mention prefix from `tracked_in_guild.ping_role_id` (else
       `guild_settings.default_ping_role_id`).
     - Send the message; on `discord.Forbidden` / `discord.NotFound`,
       log a warning, treat as success (don't block ack).
5. Concurrent DM fan-out (bounded by `dm_fanout_concurrency`):
   - `users = await bot.subs.list_subscribers_for_series(website_key, url_name)`.
   - For each user, check `dm_settings.notifications_enabled` (default
     true). Same paid-chapter respect.
   - Send DM; on `discord.Forbidden` (DMs disabled) treat as success.

Each per-guild and per-user dispatch is wrapped in a try/except so one
broken target doesn't affect the rest. After all dispatches complete, the
function returns; the consumer treats that as success and acks.

### `formatting.py` extension

`chapter_update_embed(payload: NotificationPayload) -> discord.Embed`:
- Title: `"📖 {series_title}"`.
- Description: `"New chapter: [{chapter.name}]({chapter.url})"`. Mark
  premium chapters with a `(premium)` suffix.
- Thumbnail: cover URL if present.
- Color: green for free, gold for premium.

## Tests

- `test_notification_consumer.py`:
  - Catch-up replay: with `last_acked=0`, fake server returns 3 records →
    consumer dispatches 3 in order, advances last_acked to 3, calls ack.
  - Live-during-catchup queueing: send a push while `catching_up=True`,
    then complete catch-up → push is dispatched after replay, not during.
  - Reconnect: simulate disconnect mid-stream → on reconnect, replay
    resumes from last successful ack.
- `test_notification_dispatch.py`:
  - Fake `tracked.list_guilds_tracking` returning 3 guilds; one guild has
    no channel set → skipped, others succeed.
  - Premium chapter + `paid_chapter_notifs=0` → that guild gets no message.
  - DM `Forbidden` → swallowed, doesn't fail the dispatch.

## Verification

```bash
python -m ruff check src/manhwa_bot/cogs/updates.py src/manhwa_bot/crawler/notifications.py
python -m pytest tests/test_notification_*.py -v
```

Manual against running crawler:
- Start bot; observe in logs: "catch-up complete, last_acked=N".
- On the crawler side, manually trigger `publish_new_chapters` (insert a
  chapter row + call the publisher) → bot posts in the test guild's
  notification channel within seconds.
- Stop bot. Trigger another notification on crawler. Restart bot → see
  catch-up replay log + Discord post within seconds.
- Verify `consumer_state.last_acked_notification` advanced.

## Commit message

```
Add updates cog: push-driven new-chapter dispatch + catch-up replay

Replaces v1's 25-minute polling cycle with a WebSocket push consumer.
On reconnect (and at startup), replays missed notifications via
notifications_list since the last_acked offset, then drains queued
live pushes and starts dispatching directly. Per-guild channel
resolution honors per-scanlator overrides and the paid-chapter toggle.
Per-user DM fan-out respects dm_settings.notifications_enabled.
```
