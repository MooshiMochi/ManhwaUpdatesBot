## Todo:

### Websites to add:

      Nothing at the moment...    

### Cloudflare protected websites to add:

      Nothing at the moment...

### Features to add:

- Update the /search command to use multiple scanlators (comick, mangadex, mangapill)

- When a series has been marked complete/dropped, send a notification in the updates
  channel that the series has been marked as such.

- when a user leaves the server, check if they are in any other server that the bot is also in
  and update the guild_id in the database in the users and bookmarks table to that guild id.

- make a cache decorator for the database autocomplete functions.
  note: should add a global variable that will let us know whether the db has a new entry to know whether to use cahce
  or
  not

- /info command that will display the currently available info on a manga.

- When multiple chapters are released at once, instead of sending a message for each chapter, send them all at once
    - If above implemented, when the "Mark as read/unread" button is pressed, add an aditional select where the user can
      select which chapters they want to mark as read/unread.

- When using autocomplete, prioritize the results that start with the user input, then levenshtein distance

- Implement a better global rate limiter
- (Enhancement) Create a MangaManager class that will handle all the manga related functions

### Issues:

- None known at the moment...
