/**
 * Binance's public market-data REST API — free, keyless, and explicitly
 * designed for direct browser calls (it's what Binance's own web UI uses).
 * Covers crypto only; there is no XAUUSD/EURUSD/GBPUSD/USDJPY on Binance —
 * see twelvedata.ts for those.
 */
import type { Candle } from "@/lib/candles";

const SYMBOL_MAP: Record<string, string> = {
  BTCUSD: "BTCUSDT",
};

export function binanceSymbolFor(symbol: string): string | null {
  return SYMBOL_MAP[symbol.toUpperCase()] ?? null;
}

/** Binance's interval strings ('1m','5m','15m','1h', ...) already match ours. */
export async function fetchBinanceCandles(
  symbol: string,
  timeframe: string,
  limit = 200,
): Promise<Candle[] | null> {
  const binanceSymbol = binanceSymbolFor(symbol);
  if (!binanceSymbol) return null;

  try {
    const res = await fetch(
      `https://api.binance.com/api/v3/klines?symbol=${binanceSymbol}&interval=${timeframe}&limit=${limit}`,
    );
    if (!res.ok) return null;
    const rows: unknown = await res.json();
    if (!Array.isArray(rows)) return null;
    // Each row: [openTime, open, high, low, close, volume, closeTime, ...]
    return rows.map((row) => {
      const r = row as [number, string, string, string, string, ...unknown[]];
      return { time: r[0], open: Number(r[1]), high: Number(r[2]), low: Number(r[3]), close: Number(r[4]) };
    });
  } catch {
    return null;
  }
}
