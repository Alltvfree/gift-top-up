-- 0002 — Supabase-Auth ownership + RLS (ALREADY APPLIED to the project)

ALTER TABLE bots DROP CONSTRAINT IF EXISTS bots_user_id_fkey;
ALTER TABLE broker_accounts DROP CONSTRAINT IF EXISTS broker_accounts_user_id_fkey;
DROP TABLE IF EXISTS users;

ALTER TABLE bots
    ADD CONSTRAINT bots_user_id_fkey FOREIGN KEY (user_id)
    REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE bots ALTER COLUMN user_id SET DEFAULT auth.uid();

ALTER TABLE broker_accounts
    ADD CONSTRAINT broker_accounts_user_id_fkey FOREIGN KEY (user_id)
    REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE broker_accounts ALTER COLUMN user_id SET DEFAULT auth.uid();

ALTER TABLE users            ENABLE ROW LEVEL SECURITY; -- (no-op; table dropped above in fresh installs)
ALTER TABLE broker_accounts  ENABLE ROW LEVEL SECURITY;
ALTER TABLE bots             ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders           ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_presets       ENABLE ROW LEVEL SECURITY;

CREATE POLICY bots_select_own ON bots FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY bots_insert_own ON bots FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY bots_update_own ON bots FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY bots_delete_own ON bots FOR DELETE TO authenticated USING (user_id = auth.uid());

CREATE POLICY ba_select_own ON broker_accounts FOR SELECT TO authenticated USING (user_id = auth.uid());
CREATE POLICY ba_insert_own ON broker_accounts FOR INSERT TO authenticated WITH CHECK (user_id = auth.uid());
CREATE POLICY ba_update_own ON broker_accounts FOR UPDATE TO authenticated USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
CREATE POLICY ba_delete_own ON broker_accounts FOR DELETE TO authenticated USING (user_id = auth.uid());

CREATE POLICY orders_select_own ON orders FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM bots b WHERE b.id = orders.bot_id AND b.user_id = auth.uid()));
CREATE POLICY positions_select_own ON positions FOR SELECT TO authenticated
    USING (EXISTS (SELECT 1 FROM bots b WHERE b.id = positions.bot_id AND b.user_id = auth.uid()));

CREATE POLICY ai_presets_read ON ai_presets FOR SELECT TO anon, authenticated USING (true);
