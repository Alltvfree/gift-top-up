CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS islands (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), code TEXT UNIQUE NOT NULL,
 name TEXT NOT NULL, atoll TEXT, status TEXT NOT NULL DEFAULT 'unknown'
 CHECK(status IN ('online','degraded','offline','unknown')), created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS devices (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), island_id UUID REFERENCES islands(id) ON DELETE SET NULL,
 name TEXT NOT NULL, vendor TEXT NOT NULL CHECK(vendor IN ('mikrotik','huawei','ubiquiti','other')),
 role TEXT NOT NULL CHECK(role IN ('core_router','island_router','olt','backhaul','other')),
 management_ip INET, model TEXT, software_version TEXT, status TEXT NOT NULL DEFAULT 'unknown'
 CHECK(status IN ('online','degraded','offline','unknown')), last_seen_at TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS devices_island_idx ON devices(island_id);
CREATE TABLE IF NOT EXISTS service_plans (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name TEXT UNIQUE NOT NULL,
 download_mbps INTEGER NOT NULL CHECK(download_mbps>0), upload_mbps INTEGER NOT NULL CHECK(upload_mbps>0),
 monthly_price_mvr NUMERIC(12,2) NOT NULL CHECK(monthly_price_mvr>=0), active BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE IF NOT EXISTS subscribers (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), account_number TEXT UNIQUE NOT NULL, full_name TEXT NOT NULL,
 phone TEXT, island_id UUID REFERENCES islands(id) ON DELETE SET NULL,
 plan_id UUID REFERENCES service_plans(id) ON DELETE SET NULL, pppoe_username TEXT UNIQUE,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','suspended','cancelled')),
 created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS invoices (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), subscriber_id UUID NOT NULL REFERENCES subscribers(id),
 invoice_number TEXT UNIQUE NOT NULL, amount_mvr NUMERIC(12,2) NOT NULL CHECK(amount_mvr>=0),
 due_at DATE, status TEXT NOT NULL DEFAULT 'unpaid' CHECK(status IN ('draft','unpaid','paid','overdue','void')),
 created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payments (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), subscriber_id UUID NOT NULL REFERENCES subscribers(id),
 invoice_id UUID REFERENCES invoices(id), amount_mvr NUMERIC(12,2) NOT NULL CHECK(amount_mvr>0),
 method TEXT NOT NULL CHECK(method IN ('cash','bank_transfer','card','online','other')),
 reference TEXT, received_at TIMESTAMPTZ DEFAULT now(), recorded_by TEXT
);
CREATE TABLE IF NOT EXISTS radius_sessions (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(), subscriber_id UUID REFERENCES subscribers(id) ON DELETE SET NULL,
 username TEXT NOT NULL, nas_ip INET, framed_ip INET, started_at TIMESTAMPTZ, stopped_at TIMESTAMPTZ,
 input_octets BIGINT NOT NULL DEFAULT 0, output_octets BIGINT NOT NULL DEFAULT 0,
 terminate_cause TEXT, created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit_events (
 id BIGSERIAL PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, target_type TEXT,
 target_id TEXT, detail JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ DEFAULT now()
);
