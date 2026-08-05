CREATE TABLE notification_action_contexts (
  token         TEXT PRIMARY KEY,
  website_key   TEXT NOT NULL,
  url_name      TEXT NOT NULL,
  series_url    TEXT NOT NULL,
  chapter_index INTEGER NOT NULL,
  chapter_name  TEXT,
  chapter_url   TEXT,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_notification_action_context_series
  ON notification_action_contexts(website_key, url_name, chapter_index);
