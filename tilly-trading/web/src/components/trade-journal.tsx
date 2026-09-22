"use client";

/**
 * Trade Journal card — win rate, profit factor, drawdown, the documented
 * Edge Score (github.com/LuxAlgo/trade-journal, MIT), and closed-trade
 * history. Metrics are computed client-side by @luxalgo/journal-core from
 * this bot's `positions` rows; see web/src/lib/journal.ts for the mapping
 * and its accuracy caveat.
 */
import { useEffect, useState } from "react";
import { computeEdgeScore, computeOverview, type EdgeScore, type EquityPoint, type TradeMetrics } from "@luxalgo/journal-core";
import { fetchClosedPositions, fetchPositions } from "@/lib/db";
import { positionsToRoundTrips } from "@/lib/journal";
import type { PositionRow } from "@/lib/supabase";

const money = (v: number) => `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);

export function TradeJournal() {
  const [closed, setClosed] = useState<PositionRow[]>([]);
  const [open, setOpen] = useState<PositionRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const load = () =>
      Promise.all([fetchClosedPositions(), fetchPositions()]).then(([c, o]) => {
        if (!active) return;
        setClosed(c);
        setOpen(o);
        setLoading(false);
      });
    load();
    const t = setInterval(load, 15000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, []);

  if (loading) {
    return <div className="h-24 animate-pulse rounded-lg border border-line bg-panel" />;
  }

  if (closed.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
        <div className="font-mono text-sm font-semibold text-fg">No closed trades yet</div>
        <p className="mx-auto mt-1 max-w-[260px] text-[11px] text-muted">
          History builds up as running bots close positions.
        </p>
      </div>
    );
  }

  const trades = positionsToRoundTrips([...open, ...closed]);
  const { metrics, equity } = computeOverview(trades);
  const edge = computeEdgeScore(metrics);

  return (
    <div className="space-y-3">
      <EdgeScoreCard edge={edge} netPnl={metrics.netPnl} closedTrades={metrics.closedTrades} />
      <MetricsGrid metrics={metrics} />
      {equity.length > 1 && <EquitySparkline points={equity} />}
      <ClosedTradesList positions={closed} />
    </div>
  );
}

function EdgeScoreCard({
  edge,
  netPnl,
  closedTrades,
}: {
  edge: EdgeScore;
  netPnl: number;
  closedTrades: number;
}) {
  const tone =
    edge.score === null ? "text-muted" : edge.score >= 70 ? "text-up" : edge.score >= 40 ? "text-amber" : "text-down";
  return (
    <div className="rounded-xl border border-line bg-gradient-to-b from-panel2 to-panel p-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] tracking-widest text-muted">EDGE SCORE</span>
        <span className="font-mono text-[10px] text-muted">{closedTrades} CLOSED</span>
      </div>
      <div className="mt-2 flex items-end justify-between">
        <span className={`font-mono text-[34px] font-semibold leading-none ${tone}`}>
          {edge.score === null ? "—" : Math.round(edge.score)}
        </span>
        <span className={`font-mono text-sm ${netPnl >= 0 ? "text-up" : "text-down"}`}>
          {money(netPnl)}
        </span>
      </div>
      {edge.score === null && (
        <p className="mt-2 font-mono text-[10px] text-muted">Needs 5+ closed trades to score.</p>
      )}
    </div>
  );
}

function MetricsGrid({ metrics }: { metrics: TradeMetrics }) {
  const tiles: { label: string; value: string; tone?: string }[] = [
    { label: "WIN RATE", value: pct(metrics.winRate) },
    {
      label: "PROFIT FACTOR",
      value: metrics.profitFactorIsInfinite ? "∞" : metrics.profitFactor?.toFixed(2) ?? "—",
    },
    { label: "EXPECTANCY", value: metrics.expectancy === null ? "—" : money(metrics.expectancy) },
    {
      label: "AVG WIN/LOSS",
      value: metrics.avgWinLossRatio === null ? "—" : `${metrics.avgWinLossRatio.toFixed(2)}×`,
    },
    {
      label: "MAX DRAWDOWN",
      value: metrics.maxDrawdownPct === null ? money(-metrics.maxDrawdown) : pct(-metrics.maxDrawdownPct),
      tone: "text-down",
    },
    { label: "STREAK", value: `${metrics.currentStreak >= 0 ? "+" : ""}${metrics.currentStreak}` },
  ];
  return (
    <div className="grid grid-cols-3 gap-2">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-lg border border-line bg-panel p-2.5 text-center">
          <div className={`font-mono text-sm font-semibold ${t.tone ?? "text-fg"}`}>{t.value}</div>
          <div className="mt-1 font-mono text-[9px] tracking-wide text-muted">{t.label}</div>
        </div>
      ))}
    </div>
  );
}

function EquitySparkline({ points }: { points: EquityPoint[] }) {
  const values = points.map((p) => p.cumNetPnl);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const span = max - min || 1;
  const w = 300;
  const h = 56;
  const step = points.length > 1 ? w / (points.length - 1) : w;
  const coords = values.map((v, i) => [i * step, h - ((v - min) / span) * h] as const);
  const path = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const final = values[values.length - 1] ?? 0;
  const zeroY = h - ((0 - min) / span) * h;

  return (
    <div className="rounded-lg border border-line bg-panel p-3">
      <div className="mb-2 font-mono text-[10px] tracking-widest text-muted">EQUITY CURVE</div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" preserveAspectRatio="none">
        <line x1="0" y1={zeroY} x2={w} y2={zeroY} stroke="#26344a" strokeWidth="1" />
        <path
          d={path}
          fill="none"
          stroke={final >= 0 ? "#34d399" : "#fb5d5d"}
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </div>
  );
}

function ClosedTradesList({ positions }: { positions: PositionRow[] }) {
  return (
    <div className="space-y-2">
      {positions.slice(0, 25).map((p) => {
        const pnl = p.realized_pnl;
        return (
          <div key={p.id} className="rounded-lg border border-line bg-panel p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                    p.side.toUpperCase() === "SELL"
                      ? "border-down/25 bg-down/15 text-down"
                      : "border-up/25 bg-up/15 text-up"
                  }`}
                >
                  {p.side}
                </span>
                <span className="font-mono text-sm font-semibold text-fg">{p.symbol}</span>
                <span className="font-mono text-[10px] text-muted">{p.volume}</span>
              </div>
              <span className={`font-mono text-xs ${pnl >= 0 ? "text-up" : "text-down"}`}>
                {money(pnl)}
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-muted">
              <span>ENTRY {p.open_price}</span>
              <span>{p.closed_at ? new Date(p.closed_at).toLocaleString() : "—"}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
