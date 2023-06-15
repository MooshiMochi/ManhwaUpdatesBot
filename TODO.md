## Todo:

### Websites to add:

    omegascans.org

### Cloudflare protected websites to add:

      Nothing at the moment...

### Features to add:

      - Update the /search command to use multiple scanlators (comick, mangadex, mangapill)

      - When a series has been marked complete/dropped, send a notification in the updates
      channel that the series has been marked as such.

      - when a user leaves the server, check if they are in any other server that the bot is also in
      and update the guild_id in the database in the users and bookmarsk table to that guild id.

      - make a cache decorator for the database autocomplete functions.
      note: should add a global variable that will let us know wheter the db has a new entry to know whether to use cahce or not

      - /info command that will display the currently available info on a manga.

      - Create a .sh file that will configure the system for pypetteer. (installing dependencies, etc)

### Issues:

      - reaperscans has pagination for chapters, so I need to add some code to grab all chapters...