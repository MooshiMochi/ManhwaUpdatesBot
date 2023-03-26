# ManhwaUpdatesBot

## About:

This is a bot that will periodically check for updates on the manga that you have subscribed to and alert you when there is a new chapter available.

## Requirements:

- Python 3.10+

This bot currently only supports the following websites:

- https://toonily.com
- https://manganato.com
- https://chapmanganato.com
- https://tritinia.org
- https://mangadex.org
- https://flamescans.org
- https://asurascans.com

Note: More websites will be added in the future, but only if I have some manga on it that I am reading, so don't hope for too much.

If you want to leave a suggesting of a website that I should implement for this, send me a DM over on Mooshi#6669 on discord!
Or you can contact me through my email at rchiriac16@gmail.com

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

_P.S: I am already hosting a version of this bot, so if you want to invite it to your server, here's the URL:_

   • [Invite the Bot to your server!](https://discord.com/api/oauth2/authorize?client_id=1031998059447590955&permissions=412854111296&scope=bot%20applications.commands)
  

## Todo:
   ### Websites to add: 
      en.leviathanscans.com
      luminousscans.com (maybe)
      void-scans.com
      anigliscans.com
      drakescans.com
      nitroscans.com

   ### Cloudflare protected websites to add:
      ...

   ### Features to add:
      - a bookmark feature where the user can bookmark both a completed manga and an ongoing manga
      the user will be able to edit the chapter that they've read for each bookmarked manga.
      This will most likely be done through a view.

      - a command that will show the user all the manga that they have bookmarked

      - When a series has been marked complete/dropped, send a notification in the updates
      channel that the series has been marked as such.

   ### Issues:
      - when checking for updates, sometimes a manga might be dropped. We need to account for that
      when checking whether to let the user subscribe to that series or not.
      The error message also needs to be updated to say taht the manga is either completed or dropped.

      - Rearrange the function order in each of the scanlators.py classes to follow that of the
      ABCScan class

      - Create a .sh file that will configure the system for pypetteer. 