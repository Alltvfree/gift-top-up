"use client";

/**
 * Candlestick price chart — drawn ourselves with inline SVG, no chart
 * library (an earlier @luxalgo/vela integration rendered blank on a custom
 * domain: its provider fetched our backend over CORS, which wasn't
 * allow-listed for that origin). Real data where it's available, always
 * labeled honestly (see web/src/lib/live-prices.ts for the priority order):
 * the user's own MT5 bridge, then Binance (crypto), then Twelve Data
 * (forex/gold, if configured) — falling back to the deterministic simulated
 * generator (web/src/lib/candles.ts, no network call) only when none of
 * those have data.
 */
import { useEffect, useMemo, useState } from "react";
import type { Candle } from "@/lib/candles";
import { fetchBestCandles, SOURCE_LABEL, type PriceSource } from "@/lib/live-prices";

const TIMEFRAMES = ["1m", "5m", "15m", "1h"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

const BAR_COUNT = 60;
const REFRESH_MS = 15000; // real feeds have rate limits; no need to poll faster than this

const UP = "#34d399";
const DOWN = "#fb5d5d";
const GRID = "#26344a";
const MUTED = "#6f8098";
const AMBER = "#ffb020";

// Plot viewBox (candles + gridlines). Axis labels get extra margin outside this.
const W = 600;
const H = 220;
const RIGHT_MARGIN = 54; // room for price labels
const BOTTOM_MARGIN = 18; // room for time labels

/**
 * @param liveAccountId A connected self-hosted (MT5 bridge) broker account
 *   id, if the user has one — pass null/undefined to skip straight to the
 *   public feeds.
 */
export function PriceChart({ symbol, liveAccountId }: { symbol: string; liveAccountId?: string | null }) {
  const [timeframe, setTimeframe] = useState<Timeframe>("1m");
  const [bars, setBars] = useState<Candle[]>([]);
  const [source, setSource] = useState<PriceSource | null>(null);

  useEffect(() => {
    let active = true;
    const tick = () => {
      fetchBestCandles(symbol, timeframe, BAR_COUNT, liveAccountId ?? null).then((result) => {
        if (!active) return;
        setBars(result.bars);
        setSource(result.source);
      });
    };
    tick();
    const t = setInterval(tick, REFRESH_MS);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, [symbol, timeframe, liveAccountId]);

  const geometry = useMemo(() => computeGeometry(bars), [bars]);
  const lastClose = bars.length > 0 ? bars[bars.length - 1].close : null;
  const prevClose = bars.length > 1 ? bars[bars.length - 2].close : lastClose;
  const changeUp = lastClose !== null && prevClose !== null ? lastClose >= prevClose : true;

  return (
    <div className="rounded-lg border border-line bg-panel p-2">
      <div className="mb-2 flex items-center justify-between px-1">
        <div className="flex items-baseline gap-2">
          <span
            className={`font-mono text-[10px] tracking-widest ${
              source && source !== "simulated" ? "text-up" : "text-muted"
            }`}
          >
            {symbol} · {source ? SOURCE_LABEL[source] : "…"}
          </span>
          {lastClose !== null && (
            <span className={`font-mono text-[11px] font-semibold ${changeUp ? "text-up" : "text-down"}`}>
              {formatPrice(lastClose)}
            </span>
          )}
        </div>
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              className={`rounded px-1.5 py-0.5 font-mono text-[10px] transition ${
                tf === timeframe ? "bg-amber text-ink" : "text-muted"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div className="h-[240px] w-full overflow-hidden rounded bg-ink">
        {geometry ? (
          <svg
            viewBox={`0 0 ${W} ${H + BOTTOM_MARGIN}`}
            className="h-full w-full"
            preserveAspectRatio="none"
          >
            {/* Gridlines + price labels */}
            {geometry.gridLines.map((g, i) => (
              <g key={i}>
                <line x1={0} y1={g.y} x2={W - RIGHT_MARGIN} y2={g.y} stroke={GRID} strokeWidth={1} />
                <text x={W - RIGHT_MARGIN + 4} y={g.y + 3} fontSize={9} fill={MUTED} fontFamily="monospace">
                  {formatPrice(g.price)}
                </text>
              </g>
            ))}

            {/* Candles */}
            {geometry.candles.map((c, i) => (
              <g key={i}>
                <line x1={c.x} y1={c.highY} x2={c.x} y2={c.lowY} stroke={c.up ? UP : DOWN} strokeWidth={1} />
                <rect
                  x={c.x - c.width / 2}
                  y={c.bodyTop}
                  width={c.width}
                  height={Math.max(c.bodyHeight, 1)}
                  fill={c.up ? UP : DOWN}
                />
              </g>
            ))}

            {/* Last price line */}
            {geometry.lastY !== null && (
              <line
                x1={0}
                y1={geometry.lastY}
                x2={W - RIGHT_MARGIN}
                y2={geometry.lastY}
                stroke={AMBER}
                strokeWidth={1}
                strokeDasharray="3,3"
              />
            )}

            {/* Time labels */}
            {geometry.timeLabels.map((t, i) => (
              <text key={i} x={t.x} y={H + BOTTOM_MARGIN - 4} fontSize={9} fill={MUTED} fontFamily="monospace">
                {t.label}
              </text>
            ))}
          </svg>
        ) : (
          <div className="grid h-full place-items-center">
            <span className="font-mono text-[10px] text-muted">LOADING CHART…</span>
          </div>
        )}
      </div>
    </div>
  );
}

function formatPrice(v: number): string {
  return v >= 100 ? v.toFixed(2) : v.toFixed(4);
}

interface CandleGeom {
  x: number;
  width: number;
  highY: number;
  lowY: number;
  bodyTop: number;
  bodyHeight: number;
  up: boolean;
}

interface Geometry {
  candles: CandleGeom[];
  gridLines: { y: number; price: number }[];
  timeLabels: { x: number; label: string }[];
  lastY: number | null;
}

function computeGeometry(bars: Candle[]): Geometry | null {
  if (bars.length === 0) return null;

  const highs = bars.map((b) => b.high);
  const lows = bars.map((b) => b.low);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const pad = (max - min) * 0.08 || max * 0.001;
  const top = max + pad;
  const bottom = min - pad;
  const span = top - bottom || 1;

  const plotWidth = W - RIGHT_MARGIN;
  const step = plotWidth / bars.length;
  const bodyWidth = Math.max(step * 0.6, 1);

  const priceToY = (p: number) => H - ((p - bottom) / span) * H;

  const candles: CandleGeom[] = bars.map((b, i) => {
    const x = i * step + step / 2;
    const up = b.close >= b.open;
    const bodyTopPrice = Math.max(b.open, b.close);
    const bodyBottomPrice = Math.min(b.open, b.close);
    return {
      x,
      width: bodyWidth,
      highY: priceToY(b.high),
      lowY: priceToY(b.low),
      bodyTop: priceToY(bodyTopPrice),
      bodyHeight: priceToY(bodyBottomPrice) - priceToY(bodyTopPrice),
      up,
    };
  });

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const price = bottom + span * f;
    return { y: priceToY(price), price };
  });

  const labelEvery = Math.max(Math.floor(bars.length / 4), 1);
  const timeLabels = bars
    .map((b, i) => ({ b, i }))
    .filter(({ i }) => i % labelEvery === 0)
    .map(({ b, i }) => ({
      x: i * step + step / 2,
      label: new Date(b.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    }));

  const last = bars[bars.length - 1];
  return { candles, gridLines, timeLabels, lastY: priceToY(last.close) };
}
