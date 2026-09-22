-- 0006 — self-hosted MT5 bridge provider: a small HTTP service the user runs
-- next to a real MT5 terminal (see tilly-trading/mt5-bridge/), reachable by
-- the backend at `bridge_url` with `bridge_api_key` as a bearer token.
-- connection_provider = 'self_hosted' selects this adapter (see
-- backend/app/broker/registry.py). bridge_api_key is never returned by the
-- backend API (schemas/broker.py); it's readable only via the existing
-- per-user RLS policy on broker_accounts (the owning user already gets their
-- own broker credentials back the same way metaapi_account_id works today).

ALTER TABLE broker_accounts
    ADD COLUMN IF NOT EXISTS bridge_url      VARCHAR(255),
    ADD COLUMN IF NOT EXISTS bridge_api_key  VARCHAR(255);
