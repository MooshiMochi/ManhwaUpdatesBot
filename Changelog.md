# Changelog

#### Consider supporting me on [Patreon](https://patreon.com/mooshi69) or [Ko-Fi](https://ko-fi.com/mooshi69)!

### November 2nd, 2025

+ Added new website: https://manhwabuddy.com (18+)
+ Added new website: https://arvencomics.com

### October 27th, 2025

= Modified the order in which the update message is sent. (The hidden text is displayed at the end now)

### October 24th, 2025

- Partially added a command to export tracked/subscribed/bookmarked manga from websites that are no longer supported.
    - Command (TBC): `/get_lost_manga`
    - The export will be in markdown format and will be sent as a file.
    - Note: The export will only include manga from unsupported websites.

- Added https://genzupdates.com — however, it will be disabled until a 403 bypass is found (this replaced suryatoon)
- Modified the error message for 'BotMissingPermissions'
- Updated the html_json_parser to be able to extract a single JSON object from HTML text based on JSON start key.
- Added back https://id.mgkomik.cc/
- Added https://vortexscans.org/

- Removed https://manhuaga.com as the scanlator merged into drakecomick now.
- Removed https://reaperscans.com as the scanlator is down indefinitely.

- Removed all associated ReaperScans code from the bot. That includes the API file and the custom scanlator class.

### Bug Fixes:

- Fixed arcanescans (changed tld from .com to .org)
- Fixed error in setup_hook in MangaClient.py (was accessing .config, however ._config is correct)
- Fixed comick (updated tld from .cc to .dev)
- Fixed Hivetoon (re-wrote custom implementation to keep up with the website changes)
- Fixed potential bug in method that extracts cover URL from HTML tag.
- Fixed demonreader fp conainer selector (it just ignores any ads that they decided to ad)
- Fixed flamecomics fp container selector (they changed the structure of the fp page)

## February 14th 2025

### Bug Fixes:

- Fixed bug in the update check where errors were silent causing update check tassk to restart without finishing.
- Fixed bug where /next_update_check command would throw error if it took longer than 3 seconds to respond
- Fixed bug where the pagination for /supported_websites would throw error if it took longer than 3 seconds to respond
- Updated the `get_series_to_update` method in the Database class to get series from the tracked table regardless of
  whether they're completed or not.
    - This will allow the series to be updated to the latest chapters and be removed from tracked series for the user.

## February 12th 2025

### Bug Fixes:

- Fixed bug where the cover url of a series would contain spaces. Replaced space with '%20' so it doesn't cause errors
  when it's sent as an embed. (This bug was mainly caused by demonreader)
- Fixed bug in comick where it failed to read the isoformat date due to 'Z' at the end of the date string.

## February 10th 2025

- Added https://whalemanga.com
- Added https://mangasushi.org
- Added https://manhuaga.com
- Added https://www.mgeko.cc
- Added https://templetoons.com
- Added https://platinumscans.com
- Added a new function `sort_key` in [utils.py](src/utils.py).
    - It returns a score based on the similarity of two strings.
- Removed `Docker` from the requirements section in the [README.md](./README.md) file.

## February 9th 2025

- Replaced all requests to only use the curl_cffi library.
- Added support for https://hivetoon.com.
- Fixed https://theblank.net website.
- Added back support for https://www.gyarelease.it/ as it was removed by accident.
- Fixed typo in json_map.py that made it impossible for websites to identify whether a chapter was premium or not.

- Added `_Hivescans` custom class in [custom.py](/src/core/scanlators/custom.py).
- Added a `_ChapterSelectors` class to [json_tree.py](src/core/scanlators/json_tree.py) for better typing.
- Added `R_METHOD_LITERAL` to [static.py](src/static.py) for the literal typing in request functions that take a method
  as a parameter.
- Added `is_premium` property to the `Chapter` class in [objects.py](src/core/objects.py).
- Added functionality to unload `PartialManga` objects as well in `DynamicURLScanlator` classes.
- Chapters in `PartialManga` will display a '🔒' when printed if they are premium.
- Updated `OmegaScansAPI` to use curl-based requests rather than aiohttp-based.
- Updated `ReaperScansAPI` to use curl-based requests rather than aiohttp-based.
- Updated `ZeroScansAPI` to use curl-based requests rather than aiohttp-based.
- Changed the type of the `session` parameter in the `translate` function in [utils.py](src/utils.py) to
  `CachedCurlCffiSession`.
- Removed the `CachedResponse` class from [objects.py](src/core/objects.py).
- Removed `epsilonscan` and `epsilonscansoft` from the bot (specifically
  from [lookup_map.json](src/core/scanlators/lookup_map.json).)
- Removed `lscomic` code from the bot (specifically from [lookup_map.json](src/core/scanlators/lookup_map.json).)
- Removed `CachedClientSession` class from [cache.py](src/core/cache.py) (aiohttp based) and `flaresolverr.py` (
  webserver based) from the bot.
- Added a usage for `get_from_cache` method from [cache.py](src/core/cache.py).
- Added the `search` autocomplete in the [autocomplete.py](src/ui/autocompletes.py) file as it got deleted in the
  previous update.
- Removed code for initializing and closing flaresolverrr sessions.
- Added code to check whether a chapter is premium or not for all areas where chapters are fetchd (i.e., search,
  front_page, get_all_chapters.)
- Removed flaresolverr related code from [config_loader.py](src/core/config_loader.py)
  and [config.yml.example](./config.yml.example).
- CachedCurlCffiSession now removes cached results if their status_code == 403.
- Created a Parser class in [html_json_parser.py](/src/html_json_parser.py) that parses any valid JSON from HTML text.
- Futureproofed Reaper's update check by adding support for paid chapters (I looked at novels for this).
- As a bonus, reaper now technically supports novel updates as well.
- Improved the `check_updates` method from Comick. It is now much more efficient.
- Added `get_fp_partial_manga` method to Comick.
- Added `get_fp_partial_manga` method to Mangadex.
- Added support for paid chapters to Comick
- Added a `searc` autocomplete method to the [autocompletes.py](src/ui/autocompletes.py) file.
- Added ability to extract cover from the `style` attribute of an HTML tag.
- The `check_updates` method from `AbstractScanlator` now supports paid chapters.
- Added `_build_paid_chapter_url` method to `BasicScanlator` class. It's used when the scanlator doesn't give the link
  to the paid chapter, but we can construct it using the chapter number.
- Made `json_tree.selectors.front_page.chapters` property optional in the schema file.
- Added `get_latest_chapters` method to the `ComickAPI` class.
- Added `get_latest_chapters` method to the `MangadexAPI` class.
- Modified the `get_all_chapters` method of the `ComickAPI` class to support returing chapters on a specific page.
- Updated the `/next_update_check` command. Each scanlator will have its own update check schedule.
- Added a method `extract_manga_by_command_parameter` that extracts manga object based on the command parameter.
- Added support for the `/settings` command in DMs.
- Added a warning check for the `default_ping_role` when `/settings` command is run in a server.
- Updated [config.example.yml](./config.yml.example): Removed flaresolverr related configs.
- Updated [config_loader.py](src/core/config_loader.py): Removed flaresolverr related code.
- Updated OmegaScans scanlator. Added its own `get_fp_partial_manga` method.
    - The search method now supports paid chapters as well
- Added `get_fp_partial_manga` method to ReaperScans class. It now supports paid chapters and novels too.
- Removed `ZinManga` custom class from [custom.py](src/core/scanlators/custom.py).
    - All its functionality can be achieved with the `BasicScanlator` class.
- Updated the `Database.get_series_to_update` method to only return series for a specific scanlator if needed.
- Modified the `Database.get_guild_config` method to return either `GuildSettings` or `DMSettings` object based on the
  new `user` parameter.
- Added the `get_guild_tracked_scanlators` and `is_scanlator_disabled` methods to the `Database` class.
- Added a new [html_json_parser.py](src/html_json_parser.py) file to parse JSON from an HTML text.
- Added a `supports_search` property to the JSON tree and schema file.
- Added the `_ChapterSelectors` and `_NoPremiumChapterURL` classes to the JSON tree.
- Removed AGRComics (or anigliscans) from the bot due to 403 errors on 100% of the requests made.
    - Might create a JavaScript server running Puppeteer, and see if that works.
- Removed LSComics from the bot.
- Fixed NightScans lookup map.
- Fixed ResetScans lookup map.
- Fixed Zinmanga lookup map.
- Removed AstraScans from the bot
- Removed Mangakakalot from the bot. Use manganato instead.
- Fixed Demonreader lookup map.
- Removed EpsilonScanSoft from the bot.
- Removed EpsilonScan from the bot.
- Added GyaRelease to the bot. It was previously removed by accident.
- Added `no_premium_chapter_url` to all `chapter` properties in the lookup map schema.
- Added multiple description tags to the lookup map schema.
- Added `status_changed` property to `ChapterUpdate` class.
- Changed the `Manga.available_chapters` to `Manga.chapters`
- Added a `_check_and_fix_chapters_index` that runs on the `load` and `unload` function calls in the `Manga` class.
- Added a `DMSettings` class to the `objects.py` file.
- Deleted the `CachedResponse` class from the `objects.py` file.
- Added support for paid chapters in the `omegascansAPI.py` file.
- Added support for paid chapters in the `reaperAPI.py` file.
- Added a `scrap.py` file in the `tests` folder. This file is used to test random code snippets.
- Added the `lock` emote in the `Emotes` class in the `static.py` file.
- Removed `anigliscans`, `epsilonscansoft` and `epsilonscan` from `ScanlatorsRequiringUserAgent` class in the
  `static.py`
  file.

- Complete revamp of the update check system.
    - Each scanlator can have its own update check interaval
    - Added a backup update check method that runs every 3 hours. It checks each manga for updates.

- Added the `flatten` and `find_values_by_key` method to the `utils.py` file. They are used for the new Parser.
- Updated `SettingsView` to support the `DMSettings` objects.

### Bug Fixes:

- Fixed bug in `/track` command where it would say the new updates will be sent in the default notifications channel
  instead of the scanlator association channel if it was set.
- Fixed bug in the `Database.update_series` method where the database changes weren't being committed.

## January 21st 2025

- Removed support for LSComic

## January 20th 2024

### Bug Fixes:

- Fixed test case for ataraxia (expected status was true instead of false)
- Fixed issue in update_check.py where the scanlator updates would crash if a manga had no chapters yet
- Updated asura's chapter container selector not to include paid chapters for updates. This will be redacted when the
    - option for premium chapter notifications will be introduced.

## December 22nd 2024

- Improved the search button from the bookmarks view.
- Adde rapidfuzz to requirements.txt

## // December 16th 2024

### Bug Fixes:

- Fixed asura selectors.

## // Decemper 11th 2024

- Made the search method for the scanlators optional
- Added the 'supports_search' property in the schema file

## // November 25th 2024

### Bug Fixes:

- Fixed flamecomics website
- Added support for https://www.beyondtheataraxia.com/
- Fixed asura chapter links

## // November 12th 2024

- Added `View Bookmark` button to the `Mylast read chapter` button in the chapter update message.
    - See `LastReadChapterViewBookmarkView` in [views.py](src/ui/views.py) for the implementation.
- Added `d test_update` command to dev commands.
- Moved the `BookmarkChapterView` to be loaded in the commands.py file instead of update_check.py

## // November 11th 2024

### Bug Fixes:

- Fixed scanlator association not being removed when deleting the last association.

- Added `__eq__` method for ScanlatorChannelAssociationView.
- Bookmarks automatically go to Subscribed folder when the last available chapter is marked as read.
- Renamed the buttons in the SettingsView: Done → Save; Cancel → Discard.

## // November 2nd 2024

### Bug Fixes:

- Fixed a lot of scanlator links that were broken due to changes in the website.
- Fix missing check if guild_config is None in the update check.
- Added prepare_folder method to the BookmarkView to make sure that if there's only one bookmarked manga,
  set the folder to that manga's folder


- Created a custom API class for reaperscans.
- Added json_map.rx attribute to api_based scanlators.
- Added function to automatically update comick urls to the correct ID in the database.
- Added database close method, which is called in bot.close.
- Updated database to use an open connection rather than opening a connection every time a query is run.
- Updated the function that adds the ID for dynamic scanlators.
- Added new property for dynamic ID scanlators (the location of the prefix)
- Added firescans to the bot.

## // May 15th 2024

### Bug Fixes:

- Fixed drakescans.
- Fixed nitromanga.
- Fixed nightscans.

## // March 31st 2024

### Bug Fixes:

- Fixed Kaiscans having incorrect selector for the front page cover for manhwa.
- Changed comicks domain to .io from .cc and changed the bot to use their public API insteasd.
- Attempted fix for update check on series from Asura that don't have an ID assigned yet.
- is_tracked_in_any_mutual_guild query bug fix in database.py

## // March 29th 2024

- Added new setting -> Set a bot manager role that will give you access to the track commands without requiring perms.
    - see `/settings` for this option

## // March 28th 2024

### Bug Fixes:

- Fixed failing permission check.

## // March 27th 2024

- Added EpsilonScan.fr (adult verison) to the bot.

### Bug Fixes:

- Fixed bug where bot throws error when tracking a series from asura that does not contain an ID.
- Fixed luminousscans breaking update check due to missing chapter id in front page series.

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