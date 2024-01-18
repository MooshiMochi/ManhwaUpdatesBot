# Changelog

#### Consider supporting me on [Patreon](https://patreon.com/mooshi69) or [Ko-Fi](https://ko-fi.com/mooshi69)!

## // January 18th 2024

- Moved all the config loading procedures to the config_lodaer.py file.
- Moved the json file schemas to its own folder 'schemas.'

### Bug Fixes:

- Fixed Index Error when deleting a bookmark with the 'Delete' button.

## // January 14th 2024

- Updated nightscans.net to night-scans.com.
- Added code to handle some other custom errors.

### Bug Fixes:

- Added error handling for when guild is not configured.

## // January 9th 2024

- Added support for https://mangareader.to
- Added support for https://arvenscans.org
- Added support for https://manhwa-freak.com
- Added support for https://freakscans.com
- Added support for https://mangabuddy.com
- Added support for https://topreadmanhwa.com
- Added support for https://kunmanga.com
- Added support for https://mangafire.to
- Added support for https://theblank.net
- Added support for https://nvmanga.com
- Added support for https://newmanhua.com

- The "Next Update Check..." message will automatically delete itself after 25 minutes (when the update check runs
  again)

## // January 8th 2024

- Updated the test case for Kaiscans.

### Bug Fixes:

- Fixed zeroscans. They are updated to a new domain (zscan.com)
- Fixed demoncomics. Changed it to DynamicURLScanlator type.

## // December 29th 2023

### Bug Fixes:

- Fixed reaperscans once again. They changed their domain.
- Fixed bug in bato for series that don't have the 'Upload Status' tag.

## // December 21st 2023

- Reduced the update check interval to 25 mins.
- Updated bato.to to use the v3 version of the website.
- Updated manga-demon.org to demoncomics.org
- Fixed kaiscans url.
- Updated manganato.com to manganato.to

### Bug Fixes:

- Updated comick's TLD to reflect their new API change.

## // December 8th 2023

- Updated reaperscans and reset-scans urls.
- Added the next update time to the bot's status.
- Renamed the Hidden folder to Subscribed

## // December 5th 2023

### Bug Fixes:

- Fixed Bato failing the update checks because of a URL failing the regex pattern on the website.

## // December 4th 2023

- Added the `folder` option to the `/bookmark new` and `/bookmark update` command.

### Bug Fixes:

- Fixed text view mode for the `/bookmarks view` command not displaying correct bookmarks.
- Fixed `/bookmark view` command throwing error when specifying a bookmark to view.

## // December 1st 2023

- Updated the default bookmarks folder from `All` to `Reading`.
- Added support for https://cosmic-scans.com/
- Added support for https://manga-demon.org/

## // November 28th 2023

- Added support for https://ww7.mangakakalot.tv
- Removed support for https://manhuaga.com due to the website only having 5 manhwa 💀

## // November 25th 2023

- Removed support for aquamanga.com. The website no longer exists.
- Added folders for the bookmarks.
- Added support for https://mangapark.net

## // November 10th 2023

- Added `Rizzcomic` to the list of supported websites in the README.md file.
- The bot now says, 'Processing your request' when using the `/search` command.

## Bug Fixes:

- Fixed bug where the following scenario applies (it will not happen anymore):
    - A manhwa is saved in the database, but not tracked.
    - User starts tracking the manhwa, but `x` new chapters released in the time it wasn't tracked.
    - The next update will send all `x` chapters instead of just the latest one.
    - This issue has been fixed!
- Fixed the new released update buttons didn't add the ID to the url for scanlators with dynamic IDs.
- Fixed search endpoint for Omegascans.
- Fixed the `Track and Subscribe` button from the search response showing an error.
- Renamed and moved over all stuff from flamescans.org to flamecomics.com.
- Renamed and moved over all stuff from realmscans.to to rizzcomic.com.

## // October 30th 2023

- Added `unload_disabled_scanlators` method to the bot class in `bot.py`.

### Bug Fixes:

- Implemented custom methods for omegascans `get_title`, `get_synopsis` and `get_cover`.
- Fixed the `get_chapters_list` method in `omegascansAPI.py`
- Fixed LuminousScans selector for getting front page manhwa.

## // October 22nd 2023 [Patch]

### Bug Fixes:

- Updated nigthscan's 'request_method' property to 'curl.'
- Updated Kaiscans' URL from https://kaiscans.com to https://www.kaiscans.com.
- Renamed mangabaz to nitromanga and updated its URL.
- Updated the database.get_series_to_update method's query to only get series that don't have a disabled scanlator.

## // October 18th 2023

### Bug Fixes:

- Fixed using `/bookmark update` command causing your bookmark to be hidden.

## // October 17th 2023

- Added `omegascansAPI` class to `/apis`.
- Added `zeroscansAPI` class to `/apis`.
- Added `APIManager` class to `/apis/__init__.py`
- Added support for the following websites:
    - [Kaiscans](https://kaiscans.com)
    - [Arcanescans](https://arcanescans.com)
    - [MangaBat](https://h.mangabat.com/mangabat)
    - [LHTranslation](https://lhtranslation.net/home/)
    - [Astrascans](https://astrascans.com)
    - [Ravenscans](https://ravenscans.com)
    - [Resetscans](https://reset-scans.com)
    - [Lynxscans](https://lynxscans.com)
    - [Zeroscans](https://zeroscans.com)
- Deleted `bot.comick_api` and `bot.mangadex_api` properties and replaced them with `bot.apis.comick` and
  `bot.apis.mangadex` respectively

### Bug Fixes:

- Fixed Omegascans not fetching all chapters properly if the series has multiple seasons.
- Fixed the "Unsubscribe from all untracked manhwa" button in the `/subscribe view` command unsubscribing from all
  unsubscribed manhwa in ALL servers the bot is in for the user.
- Updated LuminousScans URL to reflect their change from .com to .gg
- Fixed reaperscans sending multiple updates of the same chapter.
- Fixed reaperscans not fetching all the chapters for a manhwa properly.
- Updated the error message for when the guild is not set up yet.

## // September 28th 2023

- Added support for [MangaSiamese](https://mangasiamese.com).
- Added the `UnsupportedScanlatorURLFormatError` and `MangaNotSubscribedError` errors.
- Added ability to specify extra `params` in the `._get_text` function.
- Updated the `/supported_websites` command to use paginator if more than 10 websites are supporetd.
    - Made it automatically create the embeds as well.

### Bug Fixes:

- Changed the way mangas are identified in the database.
    - Instead of using just the id, it now uses the scanlator as well as a composite key.
- Updated void-scans `can_render_cover` and `requires_update_embed` parameters.

## // September 27th 2023

- Re-wrote the scanlator system for the bot.
    - It now uses JSON file to add websites to the bot.
        - See `lookup_map.json`.
    - Created a JSON Schema file to help with adding websites.
        - See `schema.json`
    - Added the `json_tree.py` file to represent the JSON form of a website in python
- Added ability to search by scanlator in autocomplete functions.
- Added handling for trying to start the bot when not connected to a network (offline).
- Added the `Manga.status` property (returns a String).
- Added the `get_display_embed` method for Manga class.
- Added the `More Info` button to the `SubscribeView` in `ui.views.py`
- Added the `/info` command. It will display all available info the bot has on a manhwa.
    - Removed the `/latest` command. The `/info` command has replaced its functionality
- The `/search` command will now return a list of PartialManga objects.
    - More info about a manga can be retrieved using the `More Info` button.
    - The partial manga will display the URL, Cover, Title and latest chapters.
- Moved the API classes (mangadexAPI and comickAPI) in the `./apis` folder.
- Updated the `status_update` task. It now runs every 24 hours with 20 sec between requests.
- Updated `tests.py` to use the new scanlator system.
- Updated `TODO.md`.
- Renamed the `series.completed` database column to `series.status`.
    - Changed its datatype from `BOOLEAN` to `TEXT`.
- Renamed the `series.human_name` database column to `series.title`.
- Deleted the `last_known_status` property of SCANLATORS.
- Delete SCANLATORS and relpaced it with `scanlators.scanlators`.
- Deleted the `ABCScan` and `ABCScanUtilsMixin` classes from `objects.py`
- Deleted the `scanners.py` file (rip 6+ months of work and 5.6k lines of code)
- Deleted the `overwrites.py` file. It no longer has a use.

### Bug Fixes:

- Deleted the `overwrites.Embed` class as it was causing issues with the `Embed.__eq__` method.
- Fixed Asura, Luminousscans and Flamescans URLs.
- Fixed bookmark displaying `Wait For Updates!` when the manga is marked as completed for `Next Chapter` property.
- Manually updated the URL for some comick manhwa in the database (they changed for some reason)

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