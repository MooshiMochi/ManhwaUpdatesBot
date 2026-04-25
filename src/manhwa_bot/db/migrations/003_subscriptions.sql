CREATE TABLE subscriptions (
  user_id       INTEGER NOT NULL,
  guild_id      INTEGER NOT NULL,
  website_key   TEXT NOT NULL,
  url_name      TEXT NOT NULL,
  subscribed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, guild_id, website_key, url_name)
);
CREATE INDEX idx_subscriptions_series ON subscriptions(website_key, url_name);
CREATE INDEX idx_subscriptions_user ON subscriptions(user_id);
