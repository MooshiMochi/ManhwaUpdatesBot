# Member departure subscription cleanup implementation plan

> Execute inline using the executing-plans skill; track each task below.

**Goal:** Remove only a departing member's subscriptions in the server they left and invalidate their open bookmark membership/tracking caches.

**Architecture:** Add an on_raw_member_remove listener to the already-loaded SubscriptionsCog. Reuse SubscriptionStore.unsubscribe_all_for_user(user_id, guild_id=guild_id). Track bookmark views with weak references, scoped to the bot and invoker, so event invalidation does not retain expired views. Do not fetch complete member lists.

**Tech stack:** Python 3.14.2, discord.py 2.7.1, existing SQLite store and pytest.

**Spec:** User-approved departure cleanup described in this conversation: preserve bookmarks, DM subscriptions, other users and other servers; react to leave/kick/ban without requiring cached members.

## Constraints and behavior

- Raw event payload supplies user.id and guild_id; no role-removal API calls are needed after departure.
- Delete subscriptions only, using both IDs. Repeated events and users with no subscriptions are safe.
- Invalidate open bookmark membership, tracking and track-button caches for this bot/user. Subsequent interactions recompute them; existing messages are not proactively edited.
- Report database errors through existing logging; never report successful cleanup on failure. No durable retry queue or offline reconciliation is included.
- Rejoining does not restore deleted subscriptions. Historical backups are not rewritten by this feature.
- No credentials, migrations, new dependencies, or production data are needed for tests.

## Task 1: Departure cleanup and cache invalidation

Files: modify src/manhwa_bot/cogs/subscriptions.py, src/manhwa_bot/ui/components/bookmark.py; create tests/test_member_departure.py.

- [x] Write failing tests using a real temporary SQLite database with two users, two servers, DM subscriptions and a personal bookmark. Dispatch a raw removal event and verify only the departing user's server rows disappear. Repeat the event.
- [x] Test the listener registration, an uncached event payload, preservation on database error, and invalidation of affected open bookmark views without affecting other users/bot instances.
- [x] Run `python -m pytest tests/test_member_departure.py -q` and confirm missing listener failure.
- [x] Add the listener with `await self._subs.unsubscribe_all_for_user(payload.user.id, guild_id=payload.guild_id)`; invalidate caches even when the delete fails and let the existing Discord event error handler report the exception.
- [x] Add weak view registration and `BookmarkBrowserView.invalidate_membership(bot, user_id, guild_id)`; clear dependent caches and guard async cache fills against invalidation.
- [x] Run new tests plus subscription and bookmark regressions, then ruff on changed Python files.

## Task 2: User documentation and review evidence

Files: README.md; docs/member-departure-cleanup.md; bot.py intent warning.

- [x] Explain departure deletion and preservation boundaries, rejoining behavior, missed-event limitation, and a manual test-server demonstration.
- [x] Correct the intent warning to describe departure cleanup instead of claiming role assignment requires it.
- [x] Review the diff for deletion scope, event registration, cache lifetime and failure behavior. Record test results here.
- [x] Deliver the implementation and plan with deployment status explicit. Only claim live behavior after production verification.

## Verification results

57 focused tests passed on Python 3.14.2. Ruff check and formatting passed for changed Python files. The departure and stale-button tests were observed failing before their implementation; removing the concurrency guard reproduces the in-flight membership regression. The loaded cog registry includes SubscriptionsCog. No production deployment or live Discord demonstration was performed for this feature.
