CREATE TABLE premium_grants (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  scope      TEXT NOT NULL CHECK (scope IN ('user', 'guild')),
  target_id  INTEGER NOT NULL,
  granted_by INTEGER NOT NULL,
  reason     TEXT,
  granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,
  revoked_at TIMESTAMP
);
CREATE INDEX idx_premium_grants_active ON premium_grants(scope, target_id) WHERE revoked_at IS NULL;
