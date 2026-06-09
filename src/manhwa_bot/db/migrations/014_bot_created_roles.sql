CREATE TABLE bot_created_roles (
  guild_id   INTEGER NOT NULL,
  role_id    INTEGER NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (guild_id, role_id)
);
CREATE INDEX idx_bot_created_roles_guild ON bot_created_roles(guild_id);
