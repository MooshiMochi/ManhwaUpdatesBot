ALTER TABLE guild_settings ADD COLUMN auto_create_role INTEGER NOT NULL DEFAULT 0;
ALTER TABLE guild_settings ADD COLUMN bot_manager_role_id INTEGER;
ALTER TABLE guild_settings ADD COLUMN show_update_buttons INTEGER NOT NULL DEFAULT 1;
ALTER TABLE dm_settings ADD COLUMN show_update_buttons INTEGER NOT NULL DEFAULT 1;
