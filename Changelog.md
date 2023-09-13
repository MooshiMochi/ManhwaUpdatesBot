# Changelog

#### Consider supporting me on [Patreon](https://patreon.com/mooshi69) or [Ko-Fi](https://ko-fi.com/mooshi69)!

## // September 13th 2023

- Created new `overwrites.py` file to contain all overwriting.
- Changed most instances of `discord.Embed` to `overwrites.Embed`.
- Started working on the new config system.
- Renamed the `?d sync` command to `?d pull`
- Renamed the `?d synctree` command to `?d sync` command and updated it to use Umbra's latest sync command
- Removed `/config` commands and replaced them with the `/settings` command.
- Removed webhooks from the bot alltogether (including the database).

### Bug Fixes:

- Updated NightScans TLD (top level domain) from `.org` to `.net`.
- Added internal rate limits for MangaDex API.
- Attempted to fix LuminousScans front page scraping.

## // September 10th 2023

- Renamed the `Subscribe` button to `Track and Subscribe` and updated its functionality accordingly.
  This is the button that is sent when a new chapter update is found.
- Following the above update, the emoji for the `Mark as Read` button has been changed to "☑️."
- Added the `var` parameter to CustomError for easy access to error parameters.
  It can be accessed through `error.var`.
- Allow for passing of discord.Role objects in the `Database.upsert_guild_sub_role` method.

### Bug Fixes:

- Fixed the 'Delete' button when viewing your bookmark returning "InteractionResponded" error.
- When a manhwa is marked as complete, it will ping and send an appropriate embed in the update channel.
- Fixed manhwa status not being updated in the database when made as complete.

## // September 8th 2023

- Added links to my [Patreon](https://patreon.com/mooshi69) and [Ko-Fi](https://ko-fi.com/mooshi69) in the `/help`
  command.
- Disabled the ratelimit system (for now) as it seemed redundant due to the use of rotating proxies.
- Added a text command error handler.
- Added `ABCScanMixin` class to keep the class variables separate from class methods defined in `ABCScan` class
- Improved the update check by adding the `get_front_page_partial_manwha` method to most scanlators. This allows for
  the bot to check updates in one single request instead of one request per manwha.
- Added the `Read Chapter` button to the View that appears when an update is sent.
- (Owner command) Added the option to toggle all scanlators at once with `?d tscan all` command.
- Added the `PartialManga` class to allow for partial manga objects when not all info is available.

### Bug Fixes:

- Fixed most URLs not working on Asura, Flamescans and Luminous Scans
- Fixed `/search` command returning the same result for different search queries
- Changed LeviatanScans to LSComics in the bot.
- Fixed some Regex patterns not working properly.
- Added the `load_manhwa` and `unload_manhwa` methods to `ABCScan` class
  to account for changing ID un URLs (Asura, Luminous, Flamescans, etc.)
- Updated the test cases to account for the changes in the `ABCScan` class.
- Changed the default `get_manga_id` method to only use the manhwa url name. This makes the function less error-prone.
- Fixed the `Bookmark` button in the `/search` result not working properly.
- Fixed the URL for `LSComic` in `/supported_websites` command.
- Fixed no error being sent out when bot is missing certain permissions.