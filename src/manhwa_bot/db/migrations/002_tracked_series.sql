CREATE TABLE tracked_series (
  website_key TEXT NOT NULL,
  url_name    TEXT NOT NULL,
  series_url  TEXT NOT NULL,
  title       TEXT NOT NULL,
  cover_url   TEXT,
  status      TEXT,
  added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (website_key, url_name)
);
CREATE TABLE tracked_in_guild (
  guild_id     INTEGER NOT NULL,
  website_key  TEXT NOT NULL,
  url_name     TEXT NOT NULL,
  ping_role_id INTEGER,
  added_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (guild_id, website_key, url_name),
  FOREIGN KEY (website_key, url_name) REFERENCES tracked_series(website_key, url_name) ON DELETE CASCADE
);
CREATE INDEX idx_tracked_in_guild_series ON tracked_in_guild(website_key, url_name);
