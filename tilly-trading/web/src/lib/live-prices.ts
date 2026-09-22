/**
 * Picks the best available price source for the chart, in priority order,
 * and always says which one it used — never silently shows synthetic data
 * as if it were real.
 *
 *   1. The user's own MT5 bridge (real broker history), if one is linked.
 *   2. Binance's public API, for symbols it covers (crypto only).
 *   3. Twelve Data, for forex/gold, if the user has configured an API key.
 *   4. The deterministic simulated generator — always available, never fails.
 */
import { generateCandles, liveQuote, type Candle } from "@/lib/candles";
import { fetchAccountCandles } from "@/lib/broker-api";
import { binanceSymbolFor, fetchBinanceCandles } from "@/lib/binance";
import { fetchTwelveDataCandles, twelveDataSymbolFor } from "@/lib/twelvedata";

export type PriceSource = "bridge" | "binance" | "twelvedata" | "simulated";

export interface LivePriceResult {
  bars: Candle[];
  source: PriceSource;
}

export async function fetchBestCandles(
  symbol: string,
  timeframe: string,
  limit: number,
  liveAccountId: string | null,
): Promise<LivePriceResult> {
  if (liveAccountId) {
    try {
      const bars = await fetchAccountCandles(liveAccountId, symbol, timeframe, limit);
      if (bars.length > 0) return { bars, source: "bridge" };
    } catch {
      // Provider doesn't support candles yet, bridge unreachable, CORS, etc.
      // Fall through to a public feed rather than surface this as an error.
    }
  }

  if (binanceSymbolFor(symbol)) {
    const bars = await fetchBinanceCandles(symbol, timeframe, limit);
    if (bars && bars.length > 0) return { bars, source: "binance" };
  }

  if (twelveDataSymbolFor(symbol)) {
    const bars = await fetchTwelveDataCandles(symbol, timeframe, limit);
    if (bars && bars.length > 0) return { bars, source: "twelvedata" };
  }

  return { bars: generateCandles(symbol, timeframe, limit, liveQuote(symbol)), source: "simulated" };
}

export const SOURCE_LABEL: Record<PriceSource, string> = {
  bridge: "LIVE · MT5",
  binance: "LIVE · BINANCE",
  twelvedata: "LIVE · TWELVE DATA",
  simulated: "SIMULATED",
};
