CREATE TABLE bookmarks (
  user_id           INTEGER NOT NULL,
  website_key       TEXT NOT NULL,
  url_name          TEXT NOT NULL,
  folder            TEXT NOT NULL DEFAULT 'Reading',
  last_read_chapter TEXT,
  last_read_index   INTEGER,
  created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, website_key, url_name)
);
CREATE INDEX idx_bookmarks_user_folder ON bookmarks(user_id, folder);
