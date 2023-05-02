## Todo:

### Websites to add:

    omegascans.org
    bato.to

### Cloudflare protected websites to add:

      Nothing at the moment...

### Features to add:

      - When a series has been marked complete/dropped, send a notification in the updates
      channel that the series has been marked as such.

      - in /list command, categorize the series into their scanlators
      perhaps add a select menu that will allow the user to view series for a selected scanlator.

      - optimize the check_updates function so that it requests multiple series at once (from different websites).
      Also make it so that sending updates to different webhooks happens simultaneously (probably 5 at a time)

      - when a user leaves the server, check if they are in any other server that the bot is also in
      and update the guild_id in the database in the users and bookmarsk table to that guild id.

      - make a cache decorator for the database autocomplete functions.
      note: should add a global variable that will let us know wheter the db has a new entry to know whether to use cahce or not

      - when the user marks the latest read chapter of a bookmark to be the same as the latest release, subscribe
      the user to the series if it is not complete.

      - /info command that will display the currently available info on a manga.

      - Create a .sh file that will configure the system for pypetteer. (installing dependencies, etc)

### Issues:

      - reaperscans has pagination for chapters, so I need to add some code to grab all chapters...
   
      - flamescans sometimes returns 404 when requesting. Considering switching to grabbing data with pyppeteer instead

      - mangadex needs to get all chapters. Considering using recursion or setting the limit to the number of 
        chapters in the series.