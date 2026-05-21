ALTER TABLE guild_settings ADD COLUMN update_buttons TEXT NOT NULL DEFAULT 'mark_read,bookmark,subscribe,open_chapter';
UPDATE guild_settings SET update_buttons = '' WHERE show_update_buttons = 0;
ALTER TABLE guild_settings DROP COLUMN show_update_buttons;
ALTER TABLE dm_settings ADD COLUMN update_buttons TEXT NOT NULL DEFAULT 'mark_read,bookmark,subscribe,open_chapter';
UPDATE dm_settings SET update_buttons = '' WHERE show_update_buttons = 0;
ALTER TABLE dm_settings DROP COLUMN show_update_buttons;
