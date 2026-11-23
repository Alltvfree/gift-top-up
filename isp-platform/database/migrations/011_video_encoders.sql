-- IP video encoders: reuse the devices table (identity, management IP, encrypted credentials,
-- island, via-router reachability) exactly like every other vendor, rather than a parallel table.
ALTER TABLE devices DROP CONSTRAINT devices_vendor_check;
ALTER TABLE devices ADD CONSTRAINT devices_vendor_check CHECK (vendor IN ('mikrotik','huawei','ubiquiti','encoder','other'));
ALTER TABLE devices DROP CONSTRAINT devices_role_check;
ALTER TABLE devices ADD CONSTRAINT devices_role_check CHECK (role IN ('core_router','island_router','olt','backhaul','video_encoder','other'));

-- Per-encoder settings (RTSP path/port, audio threshold, reboot limits) live in devices.settings,
-- the same free-form JSONB every other vendor already uses for its own extras.

-- One row per open-or-closed incident, separate from the generic `alerts` table (which still gets
-- a mirrored info/warning/critical row for the NOC alerts page): this one carries the diagnosis
-- and, once a verified restart adapter exists for a model, the recovery attempt and its result.
CREATE TABLE IF NOT EXISTS encoder_incidents (
 id BIGSERIAL PRIMARY KEY,
 device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK (kind IN ('network','video','audio')),
 severity TEXT NOT NULL DEFAULT 'warning' CHECK (severity IN ('warning','critical')),
 opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 closed_at TIMESTAMPTZ,
 closed_reason TEXT CHECK (closed_reason IN ('self_recovered','manual_restart','auto_restart',NULL)),
 diagnosis JSONB NOT NULL DEFAULT '{}'::jsonb,
 recovery_action TEXT CHECK (recovery_action IN ('manual_restart','auto_restart',NULL)),
 recovery_result TEXT,
 recovery_at TIMESTAMPTZ,
 recovery_by TEXT
);
CREATE INDEX IF NOT EXISTS encoder_incidents_device_idx ON encoder_incidents(device_id, opened_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS encoder_incidents_open_uniq ON encoder_incidents(device_id, kind) WHERE closed_at IS NULL;
