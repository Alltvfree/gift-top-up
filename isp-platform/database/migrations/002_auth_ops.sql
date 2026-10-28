-- Platform users, sessions, login throttling
CREATE TABLE IF NOT EXISTS users (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 username TEXT UNIQUE NOT NULL CHECK (username ~ '^[a-z0-9._-]{3,40}$'),
 full_name TEXT NOT NULL DEFAULT '',
 password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK (role IN ('admin','noc','billing','support')),
 active BOOLEAN NOT NULL DEFAULT true,
 failed_logins INTEGER NOT NULL DEFAULT 0,
 locked_until TIMESTAMPTZ,
 last_login_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 ip INET, user_agent TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
CREATE TABLE IF NOT EXISTS login_attempts (
 id BIGSERIAL PRIMARY KEY, ip INET, username TEXT, success BOOLEAN NOT NULL,
 at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS login_attempts_ip_at_idx ON login_attempts(ip, at);
CREATE INDEX IF NOT EXISTS audit_events_created_idx ON audit_events(created_at DESC);

-- Device management details. Credentials are encrypted by the API (Fernet) before storage.
ALTER TABLE devices ADD COLUMN IF NOT EXISTS parent_device_id UUID REFERENCES devices(id) ON DELETE SET NULL;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS mgmt_port INTEGER;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS credentials_enc TEXT;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS ssh_host_key TEXT;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS poll_enabled BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS notes TEXT;
-- Non-secret per-device options, e.g. {"gpon_slots":[1],"verify_tls":false}
ALTER TABLE devices ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_poll_error TEXT;
ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_role_check;
ALTER TABLE devices ADD CONSTRAINT devices_role_check
 CHECK (role IN ('core_router','island_router','olt','backhaul','radius','other'));

CREATE TABLE IF NOT EXISTS backhaul_links (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 name TEXT NOT NULL,
 kind TEXT NOT NULL CHECK (kind IN ('fiber','airfiber','other')),
 a_device_id UUID REFERENCES devices(id) ON DELETE SET NULL,
 b_device_id UUID REFERENCES devices(id) ON DELETE SET NULL,
 capacity_mbps INTEGER,
 status TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN ('online','degraded','offline','unknown')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS device_metrics (
 id BIGSERIAL PRIMARY KEY,
 device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 at TIMESTAMPTZ NOT NULL DEFAULT now(),
 reachable BOOLEAN NOT NULL,
 latency_ms REAL, packet_loss_pct REAL,
 cpu_load_pct REAL, mem_used_pct REAL, uptime_s BIGINT,
 extra JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS device_metrics_device_at_idx ON device_metrics(device_id, at DESC);

CREATE TABLE IF NOT EXISTS alerts (
 id BIGSERIAL PRIMARY KEY,
 device_id UUID REFERENCES devices(id) ON DELETE CASCADE,
 island_id UUID REFERENCES islands(id) ON DELETE CASCADE,
 severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
 kind TEXT NOT NULL,
 message TEXT NOT NULL,
 opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 resolved_at TIMESTAMPTZ,
 acknowledged_by TEXT
);
-- At most one open alert per device+kind
CREATE UNIQUE INDEX IF NOT EXISTS alerts_open_uniq ON alerts(device_id, kind) WHERE resolved_at IS NULL;

-- ONTs behind Huawei OLTs
CREATE TABLE IF NOT EXISTS onts (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 olt_device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 subscriber_id UUID REFERENCES subscribers(id) ON DELETE SET NULL,
 frame INTEGER NOT NULL, slot INTEGER NOT NULL, port INTEGER NOT NULL, ont_id INTEGER,
 serial TEXT NOT NULL, equipment_id TEXT, description TEXT,
 line_profile_id INTEGER, service_profile_id INTEGER, vlan INTEGER,
 run_state TEXT, rx_power_dbm REAL, olt_rx_power_dbm REAL, last_seen_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE (olt_device_id, serial)
);
CREATE UNIQUE INDEX IF NOT EXISTS onts_position_uniq ON onts(olt_device_id, frame, slot, port, ont_id) WHERE ont_id IS NOT NULL;

-- Change workflow: every write to a router/OLT is a reviewed plan with a rollback.
CREATE TABLE IF NOT EXISTS config_changes (
 id BIGSERIAL PRIMARY KEY,
 device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK (kind IN ('mikrotik_script','huawei_cli')),
 plan TEXT NOT NULL,
 rollback TEXT,
 status TEXT NOT NULL DEFAULT 'pending'
  CHECK (status IN ('pending','approved','rejected','applying','applied','failed','rolled_back')),
 requested_by TEXT NOT NULL,
 approved_by TEXT,
 applied_at TIMESTAMPTZ,
 result TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Subscriber extras
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS static_ip INET;
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS suspended_reason TEXT;

-- Billing periods (idempotent monthly invoicing)
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS period_start DATE;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS period_end DATE;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS paid_mvr NUMERIC(12,2) NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS invoices_sub_period_uniq ON invoices(subscriber_id, period_start) WHERE period_start IS NOT NULL;
CREATE SEQUENCE IF NOT EXISTS invoice_number_seq;
CREATE SEQUENCE IF NOT EXISTS account_number_seq START 1001;
