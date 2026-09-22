/**
 * Binance's public market-data REST API — free, keyless, and explicitly
 * designed for direct browser calls (it's what Binance's own web UI uses).
 * Binance is a crypto exchange, not a forex broker — there is no real
 * EURUSD/GBPUSD/USDJPY here, and pointing those symbols at some Binance
 * pair would mean showing the wrong instrument as if it were real, which
 * we don't do. See twelvedata.ts for those three.
 *
 * XAUUSD is the one exception: PAXG (PAX Gold) is a token backed 1:1 by
 * physical gold, redeemable for the metal — its USDT price is a genuine,
 * closely-tracking proxy for spot gold, not a guess.
 */
import type { Candle } from "@/lib/candles";

const SYMBOL_MAP: Record<string, string> = {
  BTCUSD: "BTCUSDT",
  XAUUSD: "PAXGUSDT",
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
