# ManhwaUpdatesBot

### If you want to invite the bot to your server, click [here.](https://discord.com/api/oauth2/authorize?client_id=1031998059447590955&permissions=412585675840&scope=bot%20applications.commands)

### Consider supporting me through [Ko-fi](https://ko-fi.com/mooshi69) or [Patreon](https://patreon.com/mooshi69) below.

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/Y8Y4OO6N0)
[![Patreon](https://img.shields.io/badge/Patreon-F96854?style=for-the-badge&logo=patreon&logoColor=white)](https://www.patreon.com/bePatron?u=64281496)

## About:

This is a bot that will periodically check for updates on the manga that you have subscribed to and alert you when there
is a new chapter available.

More websites will be added in the future as I find them. If you want a website to be added, please reach out to me
on the [**support server**](https://discord.gg/TYkw8VBZkr).\
Additionally, websites that are heavily protected by Cloudflare will not be added (I will list the ones I tried to
add that fit these criteria at the bottom of this file).

If you want to leave a suggestion of a website that I should implement for this, send me a DM over on `.mooshi` on
discord!

The bot can also translate messages/text to different languages using Google Translate.
You can `right-click a message > apps > Translate` to translate a message or use the `/translate` command

## Support

If you have any questions, feel free to join the [Support Server](https://discord.gg/TYkw8VBZkr) and ask there.

## Commands:

### General Commands:

`/help` - Get started with Manga Updates Bot (this message).\
`/search` - Search for a manga on supported websites.\
`/latest` - Get the latest chapter of a manga.\
`/chapters` - Get a list of chapters of a manga.\
`/next_update_check` - Get the time until the next update check.\
`/supported_websites` - Get a list of websites supported by the bot and the bot status on them.\
`/stats` - View general bot stats.\
`/patreon` - View info about the benefits you get as a Patreon.

### Config Commands:

###### (_Requires the `Manage Guild` permission._)

`/settings` - Edit the bot's settings on the server.

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

### You can view the supported websites [here.](./.github/supportedWebsites.md)

# Developers Section

## Requirements:

- Python 3.10+
- Docker (used for flaresolverr)

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

> **Note:**
> It is recommended that you use a webshare rotating proxy with backbone connection method.
> To run the test file, use the command `python -m tests`

## Contributing:

   ```
   If you want to contribute to this project, feel free to fork the repository and make a pull request.
   I will review the changes and merge them if they are good.
   ```