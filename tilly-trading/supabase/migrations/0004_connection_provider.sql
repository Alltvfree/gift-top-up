-- 0004 — provider abstraction: which MT5 connection method an account uses.
-- Values: 'metaapi' (MetaAPI cloud), 'simulated' (free paper trading),
-- and later 'self_hosted' (own MT5 gateway).

ALTER TABLE broker_accounts
  ADD COLUMN IF NOT EXISTS connection_provider VARCHAR(20) NOT NULL DEFAULT 'metaapi';
