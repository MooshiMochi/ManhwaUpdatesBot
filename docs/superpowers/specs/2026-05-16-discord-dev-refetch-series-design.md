# Discord Dev Refetch Series Design

## Goal

Add an owner-only prefix dev command to ManhwaUpdatesBot that forces crawler_backend to fetch fresh series data and overwrite the existing crawler database snapshot.

## Command Shape

The command lives under the existing `developer` group, so it is available as:

- `?d refetch <series_url>`
- `?dev refetch <series_url>`
- `?d refetch <website_key> <url_name>`
- `?dev refetch <website_key> <url_name>`

URL mode is the primary workflow. It detects `website_key` from the supported-websites cache and normalizes likely chapter URLs to series URLs with the existing `series_url_from_maybe_chapter_url` helper. The fallback workflow accepts `website_key + url_name` directly for cases where a full URL is unavailable or inconvenient.

## Data Flow

`DevCog.refetch` sends a crawler WebSocket request of type `series_data` with `refresh=True` and `allow_live=True`. URL mode sends `url=<series_url>`. Fallback mode sends `url_name=<url_name>`. The crawler service already handles live scrape, canonical identity resolution, and snapshot persistence through `resolve_series_data`.

## Output

On success, the command replies with the existing dev diagnostic UI. The response includes `website_key`, `url_name`, title, status, chapter count, and source. On crawler errors or bad arguments, it sends a concise error message consistent with existing dev commands.

## Testing

Add unit tests for argument parsing and crawler request payloads without opening Discord or network connections. Tests use the existing dev cog directly with fake `ctx`, fake bot, fake crawler, and fake supported-websites cache.
