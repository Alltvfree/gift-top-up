-- Device configuration backups (MikroTik /export, Huawei display current-configuration).
-- Content is gzip-compressed then Fernet-encrypted by the API before storage (same key as device
-- credentials) because a MikroTik export with show-sensitive carries real passwords.
CREATE TABLE IF NOT EXISTS device_backups (
 id BIGSERIAL PRIMARY KEY,
 device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 source TEXT NOT NULL CHECK (source IN ('manual','scheduled','after_change')),
 taken_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 taken_by TEXT,                        -- username for manual/after_change; NULL for scheduled
 change_id BIGINT REFERENCES config_changes(id) ON DELETE SET NULL,
 ok BOOLEAN NOT NULL,
 error TEXT,
 filename TEXT,
 size_bytes INTEGER,                   -- decompressed size, just for display
 content_enc TEXT                      -- gzip + Fernet; NULL when ok=false
);
CREATE INDEX IF NOT EXISTS device_backups_device_idx ON device_backups(device_id, taken_at DESC);
