CREATE TABLE consumer_state (
  consumer_key            TEXT PRIMARY KEY,
  last_acked_notification INTEGER NOT NULL DEFAULT 0,
  updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
