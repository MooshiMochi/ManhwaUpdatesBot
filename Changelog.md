# Changelog

#### Consider supporting me on [Patreon](https://patreon.com/mooshi69) or [Ko-Fi](https://ko-fi.com/mooshi69)!

## // March 27th 2024

- Added EpsilonScan.fr (adult verison) to the bot.

### Bug Fixes:

- Fixed bug where bot throws error when tracking a series from asura that does not contain an ID.

## // March 26th 2024

- Made SettingsView's create_embed method public.
- Added new scanlator_channel_associations table to the database.
    - Added get_used_scanlator_names method to the Database class.
    - Added get_scanlator_channel_associations method to the Database class.
    - Added upsert_scanlator_channel_associations method to the Database class.
    - Added delete_scanlator_channel_associations method to the Database class.
    - Added delete_all_scanlator_channel_associations method to the Database class.
- Updated the way ConfirmView result is being checked. This is done by a property `result.'
- Changed void-scans.com to hivescans.com.
- Changed nightscans to a dynamic url type scanlator.
- Changed TLD for reset-scans from .us to .xyz.
- Changed kaiscans to a dynamic url type scanlator and fixed some selectors.
- Changed domain of demoncomics.org to demonreader.org
- Removed Arvenscans (now known as Vortexscans) from the bot for now.
- Added `premium_status` field to the json schema.
- Added ScanlatorModal that will prompt the user to select a scanlator from the provided options available.
- Added ScanlatorChannelAssociation class to objects.py.
- Fixed the emoji string for Emotes.success.
- Added ability to redirect notifications for each scanlator to a specific channel other than the default one.
    - See `/settings` for this new feature.
- Added ScanlatorChannelAssociationView and ChannelSelectorView to the view.py file.

### Bug Fixes:

- Fixed Omegascans website being updateed (including internal API and selectors). Everything should now function
  normally.

## // February 20th 2024

- Extensions will now load to the global tree regardless of whether the bot is run in debug mode or not.
- Fixed demoncomics
- Fixed mangabat
- Added option to toggle flaresolverr in config.yml.example
- Removed print statement form update_check.py

## // February 15th 2024

- Added Webshare API wrapper to the bot
    - Added the [webshare.py](src/core/apis/webshare.py) class to the bot.
- Added FlareSolverr proxy server to the bot. It is dependent on the Webshare API Wrapepr.
    - See [flaresolverr.py](src/core/apis/flaresolverr.py) for the implementation.
- Changed the header for comick.app to use a browser header instead.
- Added `request_method` property to all implementations of the api_based.py scanlators
- Added support for the `flare` request method in classes.py and in the JSONMap.
- Removed `zinmanga` scanlator from [custom.py](src/core/scanlators/custom.py). It no longer requires custom code.
- Changed `zinmanga.io` to `zinmanga.com`. The website was probably hacked or something.
- Added EpsilonScans (soft version) to the bot. The first french scanlator to be added.
- Added logging info for the close method in the bot class.
- Updated the log_command_usage function. It will now also display the guild the command was invoked in.
    - The function has been fixed to show the actual parameters passed as it wasn't doing so for some commands.
- Removed the rateLimiter.py and rate_limiter.py files. They weren't used to begin with.
- Added `save_to_cache` method in cache.py
- database.py changes:
    - Added methods to check if a manhwa is tracked in any mutual guilds with the user in database.py
    - Also added function to remove a manhwa from being tracked if it has been marked as completed.
    - Renamed `self.client` to `self.bot` in the Database class for consistency.
    - The `get_series_to_update` method now returns a list of MangaHeader objects instead of Manga objects to save on
      memory usage.
- The `/settings` command will now display a message with warnings and how to fix them if it finds any potential issues.
- Removed the `_write_maybe_403` from the CachedResponse in objects.py. It was a waste of space...
- Added the French version of completed manhwa messages in static.py
- Added `epsilonscansoft`, `epsilonscan` and `theblank` to scanlators requiring custom headers class in static.py.
- Improved the update_check.py file as a whole. It will now be much more memory efficient.
- Added function overloading for the `group_items_by` method in the utils.py file. It should now be more type safe.
- Added `check_missing_perms` function in utils.py. It will return a list of missing permissions.
- Updated [config.example.yml](config.yml.example):
    - Added the `flaresolverr` parameter to the `api-keys` category.
    - Added the `webshare` parameter to the `api-keys` category.
    - Added `flaresolverr` category with a single parameter called `base_url`.
- Added the `/logs` folder to .gitignore. Apparently that wasn't there for some reason before.
- Added new configs to the default config setup function in utils.py
- Updated voidscans to use the `flare` request method.
- Updated mangafire to use the `flare` request method.
- Updated mangabuddy to use the `flare` request method.
- Updated freakscans to use the `flare` request method.
- Changed `luminousscas.net` to `lumitoon.com`
- Changed `zinmanga.io` to `zinmanga.com`

### Bug Fixes:

- Fixed incorrect message displayed when updating the bookmark's folder with the `/bookmark update` command.
- Fixed the embed sent for when a manhwa is marked as completed displaing text as raw text.
- Fixed the search button in the BookmarkView not working properly.
- If a bookmark is in the user's `Subscribed` folder but isn't tracked in any of the servers the user is in, the bot
  will now let them know when they move the bookmark to that folder.
- The status for mangapark is now based off of the Original Publication Status instead of the Mangapark Upload Status.
- Fixed the synopsis not being shown for some series on asura.
- Updated kaiscans properties. They made some changes to their URLs.
- Fixed loading autocomplete options for the `scanlator` parameter when using the `/search` command and not typing any
  input.
- Fixed test.py failing if there are missing configs for flaresolverr and webshare.

## // February 13th 2024

- Updated the `/bookmark update` success message to be more descriptive when providing both optional parameters.
- Added animated emotji for the `Custom Error` error.
- Added `title` attribute to the `CustomError` class in errors.py
- Added new `MangaHeader` object that holds a manga ID and scanlator.
- Updated README.md — Added `Docker` to the requirements for a future update.
- Added animated emotes to the `Emotes` class in `static.py`
- Made errors be sent to the command tree error handler for the `SubscribeView` view.

### Bug Fixes:

- Fixed autocomplete for the 'scanlator' parameter in the `/search` command when no user input is provided
- Fixed global interaction check being executed for non-command type interactions.
- Fixed command permission checks not raising the appropriate errors.

## // February 5th 2024

- Removed https://mangasiamese.com from the bot as the website no longer works.

## // January 29th 2024

- Updated the discord.py dependency to the master branch to support Entitlements.
- Updated the `/track new` command autocomplete to show only untracked and non-completed manhwa.
- Improved the autocomplete functions for the [commands.py](./src/ext/commands.py) commands.
    - Improved memory and processing efficiency by reducing the data being fetched from the database.
    - Improved the speed of the autocomplete returing results.
- Improved the auocomplete functions for the [bookmarks.py](./src/ext/bookmark.py) commands.
- Improved the `/subscribe new` command.
    - It will now show a new option `(!) All tracked series in this server`.
    - Will attempt to add all series roles if the above is selected.
    - It will no longer add the default ping role unless the above option is selected
    - If the above option is selected, it will attempt to add any remaining roles that you don't have.
- Removed the `Ping for dev updates` from `/settings` command.
- Added the `System Alerts Channel` option to `/settings` command.
  This will be the channel where you can receive dev notifications and bot warnings!
- Added a new events extension.
- Added a separate config for the System Alerts channel.
    - All dev/critical/bot alerts will be sent here instead.
- Added new errors and respective handlers for them.
- Added new database functions for the improved `/subscribe` command.
- Created a new SubscriptionObject class for the new `/subscribe` command.
- Added a `(coro) prompt` method to the `ConfirmView` class.

## // January 28th 2024

- Moved bot to new VPS.

- Added **PATREON EXCLUSIVE** feature:
    - Allows the use of commands in DMs
    - Allows tracking manhwa in DMs
- Added the `/patreon` command to view the benefits of being a Patreon.
- Added the `patreon` table to the database.
    - Added a `Patron` class to the [objects.py](./src/core/objects.py) file.
- Added the TOS and Privacy Policy links to the `/help` command.
- Added the `patreon` category to the config file.
- Added custom checks for commands. See [checks.py](./src/core/checks.py) for the code.

- Updated the [README.md](./README.md) file to look cleaner.
- Updated the `?dev sql` command.

### Bug Fixes:

- Fixed the `/stats` command showing inaccurate statistics.
- Fixed the "Search" button in the BookmarksView.

## // January 21st 2024

- Added support for https://zinmanga.io/

### Bug Fixes:

- Updated suryascans domain to suryatoon

## // January 19th 2024

- Added Terms of Service for Manhwa Updates Bot.
- Added Privacy Policy for Manhwa Updates Bot.

## // January 18th 2024

- Moved all the config loading procedures to the config_lodaer.py file.
- Moved the json file schemas to its own folder 'schemas.'
- Merged the Mangapark and Bato custom scanlator classes into one (_MagaparkAndBato).
- Changed status selectors datatype in the json_schema and lookup_map to list.

### Bug Fixes:

- Fixed Index Error when deleting a bookmark with the 'Delete' button.
- Fixed Mangapark (they stopped using the /apo/ endpoint for manhwa related content).
- Fixed Bato.to (changed the URL of their latest manhwa page).

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