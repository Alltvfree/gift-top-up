-- 0003 — broker provisioning columns (⚠️ RUN THIS ONE in the Supabase SQL editor)
-- Adds the fields the MetaAPI linking flow (Task 3) writes to broker_accounts.

ALTER TABLE broker_accounts
    ADD COLUMN IF NOT EXISTS status     VARCHAR(20)  NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS server     VARCHAR(120),
    ADD COLUMN IF NOT EXISTS platform   VARCHAR(10)  NOT NULL DEFAULT 'mt5',
    ADD COLUMN IF NOT EXISTS last_error TEXT;

-- The backend writes broker_accounts as the postgres role (bypasses RLS).
-- Existing per-user RLS policies from 0002 continue to protect browser access.
