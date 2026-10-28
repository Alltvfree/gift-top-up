-- Threat protection: failed router logins read from MikroTik logs, and a network-wide blocklist
-- pushed to every MikroTik's `blocklist` address list (dropped in RAW prerouting).
CREATE TABLE IF NOT EXISTS security_events (
 id BIGSERIAL PRIMARY KEY,
 device_id UUID REFERENCES devices(id) ON DELETE CASCADE,
 at TIMESTAMPTZ NOT NULL DEFAULT now(),
 kind TEXT NOT NULL,            -- login_failure
 src_ip INET NOT NULL,
 username TEXT,
 via TEXT,                      -- winbox | ssh | api | web ...
 message TEXT
);
CREATE INDEX IF NOT EXISTS security_events_src_at_idx ON security_events(src_ip, at DESC);
CREATE INDEX IF NOT EXISTS security_events_at_idx ON security_events(at DESC);

CREATE TABLE IF NOT EXISTS blocked_addresses (
 id BIGSERIAL PRIMARY KEY,
 address CIDR NOT NULL,
 reason TEXT NOT NULL,
 source TEXT NOT NULL CHECK (source IN ('auto','manual')),
 created_by TEXT NOT NULL,
 hits INTEGER NOT NULL DEFAULT 0,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 expires_at TIMESTAMPTZ,        -- NULL = permanent (manual only)
 removed_at TIMESTAMPTZ,
 removed_by TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS blocked_addresses_active_uniq ON blocked_addresses(address) WHERE removed_at IS NULL;

-- Per-router state: where we are in its log, and whether it actually drops the blocklist.
ALTER TABLE devices ADD COLUMN IF NOT EXISTS log_cursor BIGINT;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS blocklist_enforced BOOLEAN;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS blocklist_synced_at TIMESTAMPTZ;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS blocklist_error TEXT;
