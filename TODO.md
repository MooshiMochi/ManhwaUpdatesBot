## Todo:

### Websites to add:

      https://arcanescans.com/
      https://lynxscans.com/
      https://nocturnalscans.com/
      https://lhtranslation.net/
      https://astrascans.com/
      https://xcalibrscans.com/webcomics/
      https://ravenscans.com/
      https://zeroscans.com/

### Cloudflare protected websites to add:

      Nothing at the moment...

### Features to add:

- when a user leaves the server, check if they are in any other server that the bot is also in
  and update the guild_id in the database in the users and bookmarks table to that guild id.

- make a cache decorator for the database autocomplete functions.
  note: should add a global variable that will let us know whether the db has a new entry to know whether to use cahce
  or
  not

- When multiple chapters are released at once, instead of sending a message for each chapter, send them all at once
    - If above implemented, when the "Mark as read/unread" button is pressed, add a select where the user can
      select which chapters they want to mark as read/unread.

- When using autocomplete, prioritize the results that start with the user input, then levenshtein distance

- Create a PartialManga class that will store the manga name, manga id and manga url. Use it for search results.
- Change the Status Check function from `updates_check.py`
    - Should check it in batches.
    - Each batch should containt ~ 3 - 5 manhwa per website.
    - Example `[asura, asura, asura, toonily, toonily, toonily, ...]`
    - This way the update check function can be run MUCH quicker, and won't impact the rate limit too much.
    - Need to think about how to know which manhwas has been checked or not as loading all manhwa into memory is not
      viable.
    - Perhaps store all manhwa IDs in a SET?
    - Maybe there's a different solution.

### Issues:

Nothing here