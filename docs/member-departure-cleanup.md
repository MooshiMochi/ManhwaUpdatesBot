# Subscription cleanup when a member leaves

When Discord delivers a member departure event (leave, kick or ban), the bot deletes that user's subscriptions in that server from the active database. Personal bookmarks, reading progress, DM subscriptions, other users and other servers are preserved. Rejoining does not restore deleted subscriptions; use `/subscribe new` again.

The existing Subscriptions cog listens for `on_raw_member_remove`, so cleanup works without a cached member. `GUILD_MEMBERS` must be enabled both in the app's Discord Developer Portal settings and in the bot. No new database migration or configuration key is required.

Open bookmark views belonging to the affected user have their membership and tracking caches invalidated. They recompute status on the next interaction; already-sent Discord messages are not proactively edited. In-flight lookups retry if the departure changes their cached assumptions.

## Limits

- This responds to received events. It does not reconcile departures missed during downtime or a non-resumable disconnect.
- Database errors reach the existing event error logger. There is no durable retry queue for failed cleanup.
- Deletion applies to the active subscription table, not historical backups or all user data. Use the privacy policy contact for broader deletion requests.
- A delayed departure event can remove subscriptions created after a very rapid rejoin. The user can subscribe again after processing finishes.

## Demonstration for the intent review

1. In a private test server, configure tracking for Absolute Necromancer and subscribe a test account.
2. Give the same account a personal bookmark and, if available, a subscription in a second test server.
3. Capture the subscription list before departure.
4. Have the test account leave while the bot is online. Do not kick a real user for this test.
5. Have the account rejoin. Capture `/subscribe list` showing the first server subscription is gone, and the bookmark/second-server subscription showing those were preserved.
6. Record or screenshot the sequence and host the evidence at a reviewer-accessible URL. Do not present unit tests as a live Discord demonstration.

Suggested explanation after deployment and demonstration:

> We use Guild Members departure events to automatically delete a departing member's subscriptions for the server they leave. This prevents obsolete subscription records from accumulating and reduces retained user data. Personal bookmarks and subscriptions in other servers remain unaffected. The raw departure event supports members outside the bot's cache, without requesting complete server member lists.
