-- NSFW cover spoilering. The crawler flags NSFW covers and the bot spoilers
-- them per a configurable policy (always / never / nsfw_channel_aware).
-- Default mode is 'always'.
ALTER TABLE guild_settings ADD COLUMN nsfw_spoiler_mode TEXT NOT NULL DEFAULT 'always';
ALTER TABLE dm_settings ADD COLUMN nsfw_spoiler_mode TEXT NOT NULL DEFAULT 'always';
ALTER TABLE tracked_series ADD COLUMN is_nsfw INTEGER;
