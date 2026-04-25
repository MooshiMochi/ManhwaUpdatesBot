CREATE TABLE patreon_links (
  discord_user_id INTEGER PRIMARY KEY,
  patreon_user_id TEXT NOT NULL,
  tier_ids        TEXT NOT NULL,
  cents           INTEGER NOT NULL,
  refreshed_at    TIMESTAMP NOT NULL,
  expires_at      TIMESTAMP NOT NULL
);
