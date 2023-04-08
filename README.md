# ManhwaUpdatesBot

## About:

This is a bot that will periodically check for updates on the manga that you have subscribed to and alert you when there is a new chapter available.

## Requirements:

- Python 3.10+

This bot currently only supports the following websites:

- https://toonily.com
- https://manganato.com (alternatively known as https://chapmanganato.com)
- https://tritinia.org
- https://mangadex.org
- https://flamescans.org
- https://asurascans.com
- https://reaperscans.com
- https://anigliscans.com
- https://comick.app
- https://void-scans.com

Note: More websites will be added in the future, but only if I have some manga on it that I am reading, so don't hope for too much.
Additionally, websites that are heavily protected by Cloudflare will also not be added (I will list the ones I tried to 
add that fit these criteria at the bottom of this file).

If you want to leave a suggesting of a website that I should implement for this, send me a DM over on Mooshi#6669 on discord!
Or you can contact me through my email at rchiriac16@gmail.com

### If you want to invite the bot to your server, click [here.](https://discord.com/api/oauth2/authorize?client_id=1031998059447590955&permissions=412854111296&scope=bot%20applications.commands)
  
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


## Todo:
   ### Websites to add: 
      en.leviatanscans.com
      luminousscans.com (maybe)
      drakescans.com
      nitroscans.com
      mangapill.com

   ### Cloudflare protected websites to add:
      Nothing at the moment...

   ### Features to add:
      - When a series has been marked complete/dropped, send a notification in the updates
      channel that the series has been marked as such.

      - in /list command, categorize the series into their scanlators
      perhaps add a select menu that will allow the user to view series for a selected scanlator.

      - optimize the check_updates function so that it requests multiple series at once.
      Also make it so that sending updates to different webhooks happens simultaneously (probably 5 at a time)

      - when a user leaves the server, check if they are in any other server that the bot is also in
      and update the guild_id in the database in the users and bookmarsk table to that guild id.

      - make a cache decorator for the database autocomplete functions.
      note: should add a global variable that will let us know wheter the db has a new entry to know whether to use cahce or not

      - when the user marks the latest read chapter of a bookmark to be the same as the latest release, subscribe
      the user to the series if it is not complete.

      - /info command that will display the currently available info on a manga.

   ### Issues:
      - Create a .sh file that will configure the system for pypetteer.

      - aquamanga.org is not working on Linux. it returns 5001 error with text "enable cookies"
   
      - reaperscans has pagination for chapters, so I need to add some code to grab all chapters...

      - flamescans sometimes returns 404 when requesting. Considering switching to grabbing data with pyppeteer instead

## Contributing:
   ```
   If you want to contribute to this project, feel free to fork the repository and make a pull request.
   I will review the changes and merge them if they are good.
   ``` 

### Websites heavily protected by Cloudflare (won't be considered for this project)
   ```
   https://aquamanga.com
   ```
