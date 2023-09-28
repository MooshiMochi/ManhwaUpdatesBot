# ManhwaUpdatesBot

### If you want to invite the bot to your server, click [here.](https://discord.com/api/oauth2/authorize?client_id=1031998059447590955&permissions=412854111296&scope=bot%20applications.commands)

### Consider supporting me through [Ko-fi](https://ko-fi.com/mooshi69) or [Patreon](https://patreon.com/mooshi69).

## About:

This is a bot that will periodically check for updates on the manga that you have subscribed to and alert you when there
is a new chapter available.

More websites will be added in the future as I find them. If you want a website to be added, please reach out to me
in the [support server](https://discord.gg/5mqkKVQDYJ).\
Additionally, websites that are heavily protected by Cloudflare will not be added (I will list the ones I tried to
add that fit these criteria at the bottom of this file).

If you want to leave a suggesting of a website that I should implement for this, send me a DM over on .mooshi on
discord!

The bot can also translate messages / text to different languages using Google Translate.
You can right-click a message > apps > Translate to translate a message or use the /translate command

## Commands:

### General Commands:

`/help` - Get started with Manga Updates Bot (this message).\
`/search` - Search for a manga on MangaDex.\
`/latest` - Get the latest chapter of a manga.\
`/chapters` - Get a list of chapters of a manga.\
`/next_update_check` - Get the time until the next update check.\
`/supported_websites` - Get a list of websites supported by the bot and the bot status on them.

### Config Commands:

###### (_Requires the `Manage Guild` permission._)

`/settings` - Edit the bot's settings on the serer.

### Tracking Commands:

###### (_Requires the `Manage Roles` permission._)

`/track new` - Track a manga.\
`/track delete` - Delete a tracked manga.\
`/track list` - List all your tracked manga.

### Subscription Commands:

`/subscribe new` - Subscribe to a tracked manga.\
`/subscribe delete` - Unsubscribe from a manga.\
`/subscribe list` - List all your subscribed manga.

### Bookmark Commands:

`/bookmark new` - Bookmark a manga.\
`/bookmark view` - View your bookmarked manga.\
`/bookmark delete` - Delete a bookmark.\
`/bookmark update` - Update a bookmark.

### Miscellaneous Commands:

`/translate` - Translate with Google between languages.

## Supported Websites:

This bot currently only supports the following websites:

- https://toonily.com (requires explicit permission from the website owner)
- https://manganato.com (alternatively known as https://chapmanganato.com)
- https://tritinia.org
- https://mangadex.org
- https://flamescans.org
- https://asurascans.com
- https://reaperscans.com
- https://anigliscans.com (requires explicit permission from the website owner)
- https://comick.app
- https://luminousscans.com
- https://drakescans.com
- https://nitroscans.com
- https://mangapill.com
- https://en.leviatanscans.com
- https://aquamanga.com (requires explicit permission from the website owner)
- https://omegascans.org
- https://nightscans.org (requires explicit permission from the website owner)
- https://suryascans.com
- https://void-scans.com
- https://manhuaga.com
- https://mangasiamese.com

# Developers Section

## Requirements:

- Python 3.10+

## Setup:

How to set up the bot:

1. Cloning the repository

   ```bash
   git clone https://github.com/MooshiMochi/ManhwaUpdatesBot
   cd ManhwaUpdatesBot
   ```

2. Running the bot
   **windows:**

   ```bash
   .\run.bat
   ```

   **linux:**

   ```bash
   chmod +x run.sh setup.sh
   ./run.sh
   ```

## Notes

For developers: The following websites will not work unless a custom user-agent allowed by the owner is used:

- https://aquamanga.com
- https://anigliscans.com
- https://toonily.com

## Contributing:

   ```
   If you want to contribute to this project, feel free to fork the repository and make a pull request.
   I will review the changes and merge them if they are good.
   ``` 

### Websites heavily protected by Cloudflare (won't be considered for this project)

   ```
   Nothing here yet.
   ```

## Support

If you have any questions, feel free to join the [Support Server](https://discord.gg/TYkw8VBZkr) and ask there.
