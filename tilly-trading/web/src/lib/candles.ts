/**
 * Deterministic synthetic OHLC bars — a TypeScript port of the same
 * generator in backend/app/api/v1/market.py::_candles. Runs entirely
 * client-side: no network call, so nothing here can be blocked by CORS or
 * an unreachable backend (see the empty-chart bug this replaced). Same
 * (symbol, barIndex) always produces the same bar, so redrawing on a poll
 * tick doesn't reshuffle history — only the newest bar's close moves.
 *
 * This is flavor data for the paper-trading console, not tied to any real
 * broker feed or to a specific bot's P&L (each SimulatedBroker instance on
 * the backend runs its own independent random walk) — same honesty
 * boundary the backend version documents.
 */

export interface Candle {
  time: number; // bar open time, epoch ms
  open: number;
  high: number;
  low: number;
  close: number;
}

// Symbol -> a plausible base price, mirrors backend/app/api/v1/market.py::SYMBOLS.
const BASE_PRICES: Record<string, number> = {
  XAUUSD: 2347.5,
  EURUSD: 1.085,
  GBPUSD: 1.272,
  USDJPY: 157.3,
  BTCUSD: 64200.0,
};

const TIMEFRAME_SECONDS: Record<string, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "1h": 3600,
};

/** FNV-1a — small, fast, deterministic across browsers (no crypto needed). */
function hash32(str: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

function barPrice(symbol: string, barIndex: number): number {
  const base = BASE_PRICES[symbol.toUpperCase()] ?? 1.0;
  const seed = hash32(symbol.toUpperCase());
  const phase1 = ((seed % 1000) / 1000) * Math.PI * 2;
  const phase2 = (Math.floor(seed / 1000) % 1000) / 1000 * Math.PI * 2;
  const wave =
    Math.sin(barIndex * 0.015 + phase1) * 0.012 + Math.sin(barIndex * 0.004 + phase2) * 0.02;
  const h = hash32(`${symbol}:${barIndex}`);
  const noise = ((h % 2000) / 2000 - 0.5) * 0.004;
  return base * (1 + wave + noise);
}

/**
 * Generate `limit` bars ending at the current time. `liveClose`, if given,
 * overrides the forming (newest) bar's close — pass a live-jittered price so
 * the chart's edge can track whatever ticker price is shown elsewhere.
 */
export function generateCandles(symbol: string, timeframe: string, limit: number, liveClose?: number): Candle[] {
  const intervalMs = (TIMEFRAME_SECONDS[timeframe] ?? 60) * 1000;
  const nowMs = Date.now();
  const lastIndex = Math.floor(nowMs / intervalMs);

  const bars: Candle[] = [];
  for (let i = limit - 1; i >= 0; i--) {
    const idx = lastIndex - i;
    const openP = barPrice(symbol, idx);
    let closeP = barPrice(symbol, idx + 1);
    if (idx === lastIndex && liveClose !== undefined) closeP = liveClose;
    const span = Math.abs(closeP - openP) || openP * 0.0005;
    bars.push({
      time: idx * intervalMs,
      open: openP,
      high: Math.max(openP, closeP) + span * 0.35,
      low: Math.min(openP, closeP) - span * 0.35,
      close: closeP,
    });
  }
  return bars;
}

/** Small live jitter around a symbol's base price — same shape as the
 * backend's _simulated_quote, for a plausible-looking "current price". */
export function liveQuote(symbol: string): number {
  const base = BASE_PRICES[symbol.toUpperCase()] ?? 1.0;
  const jitter = base * (Math.random() * 0.0016 - 0.0008);
  return base + jitter;
}
