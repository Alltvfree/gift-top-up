/**
 * Client for the Tilly backend broker API (Task 3).
 *
 * Broker linking needs the server-side MetaAPI token, so it can't run in the
 * browser — it calls the deployed FastAPI backend, authenticated with the
 * user's Supabase access token. Set NEXT_PUBLIC_API_URL to the backend URL.
 */
import type { Candle } from "@/lib/candles";
import { supabase } from "@/lib/supabase";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
export const brokerApiConfigured = API_URL.length > 0;

/** Diagnostic: GET the backend /health from the browser (exercises CORS too). */
export async function pingBackend(): Promise<string> {
  if (!brokerApiConfigured) return "NEXT_PUBLIC_API_URL not set";
  try {
    const res = await fetch(`${API_URL}/health`, { method: "GET" });
    const body = await res.text();
    return `GET ${res.status} · ${body.slice(0, 120)}`;
  } catch (e) {
    return `GET failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

/** Diagnostic: check the backend's database connection. */
export async function pingDB(): Promise<string> {
  if (!brokerApiConfigured) return "NEXT_PUBLIC_API_URL not set";
  try {
    const res = await fetch(`${API_URL}/dbcheck`, { method: "GET" });
    return `DB ${res.status} · ${(await res.text()).slice(0, 220)}`;
  } catch (e) {
    return `DB check failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

/** Diagnostic: authenticated POST (same auth+CORS path as linking, but instant). */
export async function pingAuthedPost(): Promise<string> {
  if (!brokerApiConfigured) return "NEXT_PUBLIC_API_URL not set";
  try {
    const res = await fetch(`${API_URL}/api/v1/broker/ping`, {
      method: "POST",
      headers: await authHeaders(),
      body: JSON.stringify({}),
    });
    const body = await res.text();
    return `POST ${res.status} · ${body.slice(0, 160)}`;
  } catch (e) {
    return `POST failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

export interface LinkBrokerInput {
  broker_name: string;
  login: string;
  password: string;
  server: string;
  platform: "mt4" | "mt5";
  account_type: "demo" | "live";
}

export interface LinkMt5BridgeInput {
  broker_name: string;
  bridge_url: string;
  bridge_api_key: string;
  account_type: "demo" | "live";
}

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function addPaperAccount(): Promise<void> {
  if (!brokerApiConfigured) {
    throw new Error("Backend not configured (NEXT_PUBLIC_API_URL is not set).");
  }
  const res = await fetch(`${API_URL}/api/v1/broker/paper`, {
    method: "POST",
    headers: await authHeaders(),
    body: "{}",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
}

export async function linkBroker(input: LinkBrokerInput): Promise<void> {
  if (!brokerApiConfigured) {
    throw new Error("Backend not configured (NEXT_PUBLIC_API_URL is not set).");
  }
  const res = await fetch(`${API_URL}/api/v1/broker/link`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
}

/**
 * Real OHLC history from a linked broker account's own connection (the MT5
 * bridge, currently the only provider that implements it). Throws on any
 * failure — including a 501 from a provider that doesn't support candles —
 * callers should catch this and fall back to a public feed / the simulated
 * chart rather than surface it as an error.
 */
export async function fetchAccountCandles(
  accountId: string,
  symbol: string,
  timeframe: string,
  limit = 200,
): Promise<Candle[]> {
  if (!brokerApiConfigured) throw new Error("Backend not configured.");
  const qs = new URLSearchParams({ symbol, timeframe, limit: String(limit) });
  const res = await fetch(`${API_URL}/api/v1/broker/accounts/${accountId}/candles?${qs}`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`candles ${res.status}`);
  const body: { bars?: Candle[] } = await res.json();
  return body.bars ?? [];
}

/**
 * This account's real broker-side symbol names (MT5 bridge only — other
 * providers 501, callers should fall back to a fixed list). Powers the New
 * Bot wizard's symbol picker so the user doesn't have to guess whether
 * their broker suffixes symbols (XAUUSD vs XAUUSDm).
 */
export async function fetchAccountSymbols(accountId: string): Promise<string[]> {
  if (!brokerApiConfigured) throw new Error("Backend not configured.");
  const res = await fetch(`${API_URL}/api/v1/broker/accounts/${accountId}/symbols`, {
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`symbols ${res.status}`);
  const body: { symbols?: string[] } = await res.json();
  return body.symbols ?? [];
}

/**
 * Link a self-hosted MT5 bridge (tilly-trading/mt5-bridge/) — a small HTTPS
 * service the user runs themselves next to a real MT5 terminal, instead of
 * provisioning through MetaAPI. The backend verifies it live (a health check
 * + account fetch) before saving, so a bad URL/key fails immediately.
 */
export async function linkMt5Bridge(input: LinkMt5BridgeInput): Promise<void> {
  if (!brokerApiConfigured) {
    throw new Error("Backend not configured (NEXT_PUBLIC_API_URL is not set).");
  }
  const res = await fetch(`${API_URL}/api/v1/broker/mt5-bridge`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
}
