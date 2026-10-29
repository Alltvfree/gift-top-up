-- ONT details read on each OLT poll
ALTER TABLE onts ADD COLUMN IF NOT EXISTS temperature_c REAL;
ALTER TABLE onts ADD COLUMN IF NOT EXISTS polled_at TIMESTAMPTZ;
ALTER TABLE onts ADD COLUMN IF NOT EXISTS control TEXT;  -- active | deactivated (ont activate/deactivate)
CREATE INDEX IF NOT EXISTS onts_olt_idx ON onts(olt_device_id, frame, slot, port, ont_id);
