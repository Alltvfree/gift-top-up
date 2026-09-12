-- 0005 — store the reason a bot failed to start, for visibility in the UI.
ALTER TABLE bots ADD COLUMN IF NOT EXISTS last_error TEXT;
