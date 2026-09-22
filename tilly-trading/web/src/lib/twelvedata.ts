/**
 * Twelve Data's REST API for forex (EURUSD, GBPUSD, USDJPY — Binance has no
 * real forex data at all; XAUUSD is covered live via Binance's PAXG token
 * instead, see binance.ts, but kept here too as a second opinion if that
 * ever fails). "Fastest live platform, no signup" means we default to
 * Twelve Data's public `demo` key rather than wait on the user to register
 * for their own — it's real but shared and rate-limited (documented on
 * Twelve Data's own site as a live testing key, not a production one). Set
 * NEXT_PUBLIC_TWELVEDATA_API_KEY in Cloudflare Pages' build env to a real
 * free-tier key (twelvedata.com/pricing) for reliable, non-shared use.
 *
 * ⚠️ Unverified from this repo's dev environment: outbound network access
 * here is restricted to a small allowlist that doesn't include
 * api.twelvedata.com, so this was written against Twelve Data's documented
 * contract (stable/widely used) but never actually called — including
 * whether the `demo` key still works or has since been restricted/removed.
 * Test it and check the chart's source label; if the demo key doesn't
 * work, fetchTwelveDataCandles's shape guard makes it fall back to the
 * simulated series rather than show garbage, and getting your own free key
 * is the fix.
 */
import type { Candle } from "@/lib/candles";

const SYMBOL_MAP: Record<string, string> = {
  XAUUSD: "XAU/USD",
  EURUSD: "EUR/USD",
  GBPUSD: "GBP/USD",
  USDJPY: "USD/JPY",
};

const DEMO_API_KEY = "demo";

const INTERVAL_MAP: Record<string, string> = {
  "1m": "1min",
  "5m": "5min",
  "15m": "15min",
  "1h": "1h",
};

export function twelveDataSymbolFor(symbol: string): string | null {
  return SYMBOL_MAP[symbol.toUpperCase()] ?? null;
}

interface TwelveDataValue {
  datetime: string;
  open: string;
  high: string;
  low: string;
  close: string;
}

export async function fetchTwelveDataCandles(
  symbol: string,
  timeframe: string,
  limit = 200,
): Promise<Candle[] | null> {
  const apiKey = process.env.NEXT_PUBLIC_TWELVEDATA_API_KEY || DEMO_API_KEY;
  const tdSymbol = twelveDataSymbolFor(symbol);
  if (!tdSymbol) return null;
  const interval = INTERVAL_MAP[timeframe] ?? "1min";

  const url =
    `https://api.twelvedata.com/time_series?symbol=${encodeURIComponent(tdSymbol)}` +
    `&interval=${interval}&outputsize=${limit}&timezone=UTC&apikey=${apiKey}`;

  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const body: { status?: string; values?: TwelveDataValue[] } = await res.json();
    if (body.status === "error" || !Array.isArray(body.values)) return null;

    // Twelve Data returns newest-first; we want ascending like every other source.
    return body.values
      .map((v) => ({
        time: Date.parse(`${v.datetime.replace(" ", "T")}Z`),
        open: Number(v.open),
        high: Number(v.high),
        low: Number(v.low),
        close: Number(v.close),
      }))
      .filter((b) => Number.isFinite(b.time) && Number.isFinite(b.close))
      .reverse();
  } catch {
    return null;
  }
}
