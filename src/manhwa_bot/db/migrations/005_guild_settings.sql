CREATE TABLE guild_settings (
  guild_id                 INTEGER PRIMARY KEY,
  notifications_channel_id INTEGER,
  system_alerts_channel_id INTEGER,
  default_ping_role_id     INTEGER,
  paid_chapter_notifs      INTEGER NOT NULL DEFAULT 1,
  updated_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE guild_scanlator_channels (
  guild_id    INTEGER NOT NULL,
  website_key TEXT NOT NULL,
  channel_id  INTEGER NOT NULL,
  PRIMARY KEY (guild_id, website_key),
  FOREIGN KEY (guild_id) REFERENCES guild_settings(guild_id) ON DELETE CASCADE
);
