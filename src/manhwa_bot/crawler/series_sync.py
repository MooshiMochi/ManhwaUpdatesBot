from __future__ import annotations

import logging
from typing import Any

from ..db.bookmarks import BookmarkStore
from ..db.subscriptions import SubscriptionStore
from ..db.tracked import TrackedStore

_log = logging.getLogger(__name__)


def collect_series_reference_refs(
    *,
    bookmark_refs: list[dict[str, Any]],
    tracked_refs: list[dict[str, Any]],
    subscription_refs: list[dict[str, Any]],
) -> list[dict[str, int | str]]:
    combined: dict[tuple[str, str], dict[str, int | str]] = {}

    def row_for(ref: dict[str, Any]) -> dict[str, int | str] | None:
        website_key = str(ref.get("website_key") or "").strip()
        url_name = str(ref.get("url_name") or "").strip()
        if not website_key or not url_name:
            return None
        key = (website_key, url_name)
        row = combined.get(key)
        if row is None:
            row = {
                "website_key": website_key,
                "url_name": url_name,
                "bookmarks": 0,
                "tracked": 0,
                "subscriptions": 0,
            }
            combined[key] = row
        return row

    for ref in bookmark_refs:
        row = row_for(ref)
        if row is not None:
            row["bookmarks"] = int(row["bookmarks"]) + int(ref.get("bookmarks") or 0)
    for ref in tracked_refs:
        row = row_for(ref)
        if row is not None:
            row["tracked"] = int(row["tracked"]) + int(ref.get("tracked") or 0)
    for ref in subscription_refs:
        row = row_for(ref)
        if row is not None:
            row["subscriptions"] = int(row["subscriptions"]) + int(ref.get("subscriptions") or 0)

    return [combined[key] for key in sorted(combined, key=lambda item: (item[0], item[1]))]


def crawler_client_id(config: Any) -> str:
    crawler = getattr(config, "crawler", None)
    configured = str(getattr(crawler, "client_id", "") or "").strip()
    if configured:
        return configured
    consumer_key = str(getattr(crawler, "consumer_key", "") or "").strip()
    return consumer_key or "manhwa-bot"


async def handle_series_sync_request(bot: Any, envelope: dict[str, Any]) -> None:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    sync_request_id = str(data.get("request_id") or envelope.get("request_id") or "").strip()
    ttl_days = int(data.get("client_reference_ttl_days") or 365)

    bookmarks = BookmarkStore(bot.db)
    tracked = TrackedStore(bot.db)
    subscriptions = SubscriptionStore(bot.db)
    refs = collect_series_reference_refs(
        bookmark_refs=await bookmarks.list_distinct_series_refs(),
        tracked_refs=await tracked.list_distinct_series_refs(),
        subscription_refs=await subscriptions.list_distinct_series_refs(),
    )
    await bot.crawler.request(
        "series_sync_submit",
        sync_request_id=sync_request_id,
        client_id=crawler_client_id(bot.config),
        client_reference_ttl_days=ttl_days,
        refs=refs,
    )
    _log.info(
        "submitted %d series references to crawler sync request %s", len(refs), sync_request_id
    )


def register_series_sync_handler(bot: Any) -> None:
    bot.crawler.on_push(
        "series_sync_request",
        lambda envelope: handle_series_sync_request(bot, envelope),
    )
