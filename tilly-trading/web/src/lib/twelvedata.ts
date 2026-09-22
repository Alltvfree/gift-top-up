/**
 * Twelve Data's REST API for forex + gold (XAUUSD, EURUSD, GBPUSD, USDJPY —
 * none of which Binance carries). Free tier requires your own API key
 * (twelvedata.com/pricing — the free plan covers this at a light poll rate);
 * set NEXT_PUBLIC_TWELVEDATA_API_KEY in Cloudflare Pages' build env. Skipped
 * entirely with no key configured — callers fall back further, never break.
 *
 * ⚠️ Unverified from this repo's dev environment: outbound network access
 * here is restricted to a small allowlist that doesn't include
 * api.twelvedata.com, so this was written against Twelve Data's documented
 * contract (stable/widely used) but never actually called. Test it once a
 * key is configured — if the shape has drifted, fetchTwelveDataCandles
 * returns null (see the shape guard below) and the chart falls back to the
 * simulated series rather than showing garbage.
 */
import type { Candle } from "@/lib/candles";

const SYMBOL_MAP: Record<string, string> = {
  XAUUSD: "XAU/USD",
  EURUSD: "EUR/USD",
  GBPUSD: "GBP/USD",
  USDJPY: "USD/JPY",
};

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
  const apiKey = process.env.NEXT_PUBLIC_TWELVEDATA_API_KEY;
  if (!apiKey) return null;
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
