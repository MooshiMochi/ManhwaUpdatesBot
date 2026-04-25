CREATE TABLE dm_settings (
  user_id               INTEGER PRIMARY KEY,
  notifications_enabled INTEGER NOT NULL DEFAULT 1,
  paid_chapter_notifs   INTEGER NOT NULL DEFAULT 1,
  updated_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
