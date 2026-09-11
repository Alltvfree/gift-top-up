import { createClient } from "@supabase/supabase-js";

/**
 * Supabase browser client. The URL and publishable key are safe to ship to the
 * browser (that's what the publishable/anon key is for) — data is protected by
 * Row Level Security, not by hiding the key.
 *
 * Values come from env vars when set (e.g. Cloudflare Pages build vars), and
 * fall back to this project's values so the app works with zero config.
 */
export const SUPABASE_URL =
  process.env.NEXT_PUBLIC_SUPABASE_URL || "https://vvkddynlfgilymzvugfo.supabase.co";

export const SUPABASE_ANON_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  "sb_publishable_RcfbwbF2ubNMG5sfKxKRhA_57IUq1Sh";

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

// ---- Row types (mirror the Supabase tables) ----
export interface BotRow {
  id: string;
  user_id: string;
  broker_account_id: string | null;
  name: string;
  strategy: "GRID" | "DCA";
  symbol: string;
  status: "stopped" | "running" | "paused" | "error";
  parameters: Record<string, unknown>;
  ai_preset_used: string | null;
  total_pnl: number;
  created_at: string;
  started_at: string | null;
  stopped_at: string | null;
}

export interface PositionRow {
  id: string;
  bot_id: string;
  symbol: string;
  side: string;
  volume: number;
  open_price: number;
  current_price: number | null;
  unrealized_pnl: number;
  realized_pnl: number;
  opened_at: string;
  closed_at: string | null;
}

export interface BrokerAccountRow {
  id: string;
  broker_name: string;
  account_id: string;
  account_type: string;
  balance: number | null;
  currency: string;
  is_active: boolean;
  status: string | null;
  server: string | null;
  platform: string | null;
  metaapi_account_id: string | null;
  last_error: string | null;
  created_at: string;
}

export interface PresetRow {
  id: string;
  name: string;
  risk_level: number;
  default_parameters: Record<string, number>;
}
