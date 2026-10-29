-- Telegram bot: change approvals (with a 2FA code) and alerts, per linked platform user.
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_name TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_linked_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_alerts BOOLEAN NOT NULL DEFAULT true;

-- One-time codes from My account -> Connect Telegram (sha256 of the code, 10 minutes).
CREATE TABLE IF NOT EXISTS telegram_link_codes (
 code_hash TEXT PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TIMESTAMPTZ NOT NULL
);

-- Written by the API/worker, sent by the bot service.
--   change_request: post change_id with buttons to chat_id
--   refresh:        re-render every posted message of change_id (status changed)
--   text:           plain message to chat_id
CREATE TABLE IF NOT EXISTS telegram_outbox (
 id BIGSERIAL PRIMARY KEY,
 kind TEXT NOT NULL CHECK (kind IN ('change_request','refresh','text')),
 chat_id BIGINT,
 change_id BIGINT REFERENCES config_changes(id) ON DELETE CASCADE,
 body TEXT,
 attempts INTEGER NOT NULL DEFAULT 0,
 error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 sent_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS telegram_outbox_queue ON telegram_outbox(id) WHERE sent_at IS NULL;

-- Where each change was posted, so the buttons can be replaced once someone acts on it.
CREATE TABLE IF NOT EXISTS telegram_change_messages (
 change_id BIGINT NOT NULL REFERENCES config_changes(id) ON DELETE CASCADE,
 chat_id BIGINT NOT NULL,
 message_id BIGINT NOT NULL,
 PRIMARY KEY (chat_id, message_id)
);
CREATE INDEX IF NOT EXISTS telegram_change_messages_change ON telegram_change_messages(change_id);

-- A button was pressed; the bot waits for the user's 6-digit code to confirm it.
CREATE TABLE IF NOT EXISTS telegram_pending (
 chat_id BIGINT PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 change_id BIGINT NOT NULL REFERENCES config_changes(id) ON DELETE CASCADE,
 action TEXT NOT NULL CHECK (action IN ('approve','approve_apply','apply')),
 attempts INTEGER NOT NULL DEFAULT 0,
 expires_at TIMESTAMPTZ NOT NULL
);

-- Bot bookkeeping: getUpdates offset, bot username (for the t.me link shown in the portal).
CREATE TABLE IF NOT EXISTS telegram_state (
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);
