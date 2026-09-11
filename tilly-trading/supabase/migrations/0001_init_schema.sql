-- 0001 — initial Tilly Trading schema (ALREADY APPLIED to the project)
-- Kept here for the record / to recreate the database from scratch.

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    subscription_tier VARCHAR(50) NOT NULL DEFAULT 'free',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS broker_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    broker_name VARCHAR(50) NOT NULL,
    account_id VARCHAR(100) NOT NULL,
    account_type VARCHAR(20) NOT NULL DEFAULT 'live',
    balance NUMERIC(15,2),
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metaapi_account_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    broker_account_id UUID REFERENCES broker_accounts(id),
    name VARCHAR(100) NOT NULL,
    strategy VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'stopped',
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    ai_preset_used VARCHAR(50),
    total_pnl NUMERIC(15,2) NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    broker_order_id VARCHAR(100),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    type VARCHAR(20) NOT NULL,
    price NUMERIC(15,5),
    volume NUMERIC(10,3) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    filled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    broker_position_id VARCHAR(100),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    volume NUMERIC(10,3) NOT NULL,
    open_price NUMERIC(15,5) NOT NULL,
    current_price NUMERIC(15,5),
    unrealized_pnl NUMERIC(15,2) NOT NULL DEFAULT 0,
    realized_pnl NUMERIC(15,2) NOT NULL DEFAULT 0,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ai_presets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL,
    risk_level INTEGER NOT NULL,
    default_parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_bots_user_id ON bots(user_id);
CREATE INDEX IF NOT EXISTS ix_orders_bot_id ON orders(bot_id);
CREATE INDEX IF NOT EXISTS ix_positions_bot_id ON positions(bot_id);
CREATE INDEX IF NOT EXISTS ix_broker_accounts_user_id ON broker_accounts(user_id);
