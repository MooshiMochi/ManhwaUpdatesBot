CREATE TABLE migration_resolutions (
  scope          TEXT NOT NULL CHECK (scope IN ('subscription','bookmark','guild_tracking')),
  owner_id       INTEGER NOT NULL,
  v1_scanlator   TEXT NOT NULL,
  v1_url         TEXT NOT NULL,
  v2_website_key TEXT,              -- NULL = user skipped this leftover
  v2_url_name    TEXT,
  resolved_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (scope, owner_id, v1_scanlator, v1_url)
);
CREATE INDEX idx_migration_resolutions_owner ON migration_resolutions(owner_id, scope);
