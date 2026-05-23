CREATE TABLE notification_mark_read_toggles (
  user_id                    INTEGER NOT NULL,
  website_key                TEXT NOT NULL,
  url_name                   TEXT NOT NULL,
  chapter_index              INTEGER NOT NULL,
  previous_bookmark_exists   INTEGER NOT NULL,
  previous_folder            TEXT,
  previous_last_read_chapter TEXT,
  previous_last_read_index   INTEGER,
  created_at                 TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, website_key, url_name, chapter_index)
);
CREATE INDEX idx_notification_mark_read_toggles_user
  ON notification_mark_read_toggles(user_id, website_key, url_name);
