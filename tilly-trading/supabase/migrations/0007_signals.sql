-- 0007 — signals table: market forecasts from an external model (e.g. Kronos,
-- the local LightGBM signal generator), consumed by the frontend Signals
-- page and, later, as an optional entry filter bots can check before opening
-- a position. Not tied to any one user/account — a symbol's forecast is the
-- same for everyone, so it's a shared-read table like ai_presets, not
-- ownership-scoped like bots/positions.

CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,           -- BUY | SELL | NO_TRADE
    confidence NUMERIC NOT NULL,          -- 0-100
    timeframe VARCHAR(10) NOT NULL,       -- e.g. M5, M15, H1
    tp NUMERIC,
    sl NUMERIC,
    expected_move NUMERIC,                -- percent, signed
    note TEXT,
    source VARCHAR(50) NOT NULL DEFAULT 'kronos',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_signals_symbol_created ON signals(symbol, created_at DESC);

ALTER TABLE signals ENABLE ROW LEVEL SECURITY;

-- Every signed-in user (and the frontend's anon key before sign-in isn't
-- used for this page, but anon is included for consistency with
-- ai_presets_read) can read every signal — it's a shared market forecast,
-- not per-account data.
CREATE POLICY signals_read ON signals FOR SELECT TO anon, authenticated USING (true);

-- Deliberately no INSERT/UPDATE/DELETE policy for anon/authenticated: only
-- the service_role key (used directly by Kronos on its own machine, never
-- exposed to the browser or committed anywhere) can write, since
-- service_role bypasses RLS by design. This keeps forecast-writing out of
-- reach of anything running in the browser.
