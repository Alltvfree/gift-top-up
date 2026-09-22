"use client";

/**
 * Candlestick price chart, powered by LuxAlgo's Vela (Apache-2.0, WebGL2).
 * Fed by our own simulated market-data endpoint via `tillyMarketProvider` —
 * no external broker/exchange call, so it works with the paper provider and
 * any future broker the same way. See web/src/lib/vela-provider.ts.
 */
import { useEffect, useRef, useState } from "react";
import { Vela } from "@luxalgo/vela";
import { tillyMarketProvider } from "@/lib/vela-provider";

const CHART_THEME = {
  background: "#070b11",
  textColor: "#e2e8f0",
  gridColor: "#16202f",
  borderColor: "#26344a",
  upColor: "#34d399",
  downColor: "#fb5d5d",
  fontFamily: "var(--font-mono), ui-monospace, monospace",
};

const TIMEFRAMES = ["1m", "5m", "15m", "1h"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];
const PROVIDER_NAME = "tilly";

export function PriceChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<InstanceType<typeof Vela> | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("1m");
  const [ready, setReady] = useState(false);

  // Mount/tear down the chart once per symbol (a fresh identity, not a param
  // tweak, so a clean re-create is simpler than reasoning about setMarket's
  // in-place switch across unrelated symbols).
  useEffect(() => {
    if (!containerRef.current) return;
    setReady(false);
    const chart = new Vela(containerRef.current, {
      symbol: `${PROVIDER_NAME}:${symbol}`,
      timeframe,
      theme: CHART_THEME,
      live: true,
      drawings: false,
    });
    chart.data.registerProvider(PROVIDER_NAME, tillyMarketProvider);
    chartRef.current = chart;
    chart.ready().then(() => setReady(true));

    return () => {
      chart.destroy();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  // Timeframe changes switch the market in place on the live chart.
  useEffect(() => {
    chartRef.current?.setMarket({ timeframe });
  }, [timeframe]);

  return (
    <div className="rounded-lg border border-line bg-panel p-2">
      <div className="mb-2 flex items-center justify-between px-1">
        <span className="font-mono text-[10px] tracking-widest text-muted">
          {symbol} · SIMULATED
        </span>
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
      <div className="relative h-[260px] w-full overflow-hidden rounded">
        {!ready && (
          <div className="absolute inset-0 grid place-items-center bg-panel">
            <span className="font-mono text-[10px] text-muted">LOADING CHART…</span>
          </div>
        )}
        <div ref={containerRef} className="h-full w-full" />
      </div>
    </div>
  );
}
