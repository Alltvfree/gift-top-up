"use client";

import { useEffect, useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { fetchSignals } from "@/lib/db";
import type { SignalRow } from "@/lib/supabase";

export default function SignalsPage() {
  return (
    <ConsoleShell>
      <Signals />
    </ConsoleShell>
  );
}

function Signals() {
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const load = (silent: boolean) => {
      fetchSignals()
        .then((rows) => {
          if (active) setSignals(rows);
        })
        .finally(() => {
          if (active && !silent) setLoading(false);
        });
    };
    load(false);
    // Signals update on a model's own cadence (e.g. every closed M5 candle),
    // far slower than positions — a 15s poll is plenty responsive without
    // hammering Supabase.
    const t = setInterval(() => load(true), 15000);
    return () => {
      active = false;
      clearInterval(t);
    };
  }, []);

  const latest = signals[0] ?? null;

  return (
    <>
      <h1 className="font-mono text-xs tracking-widest text-muted">SIGNAL FEED</h1>

      <section className="rounded-xl border border-line bg-gradient-to-b from-panel2 to-panel p-4">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] tracking-widest text-muted">LATEST FORECAST</span>
          <span className="font-mono text-[11px] text-amber">
            {latest ? `${latest.timeframe} · ${latest.source.toUpperCase()}` : "—"}
          </span>
        </div>
        {loading ? (
          <div className="mt-3 h-10 animate-pulse rounded bg-panel2" />
        ) : latest ? (
          <>
            <div className="mt-2 flex items-end gap-2">
              <span
                className={`font-mono text-[26px] font-semibold leading-none tracking-tight ${
                  latest.side === "BUY"
                    ? "text-up"
                    : latest.side === "SELL"
                      ? "text-down"
                      : "text-fg"
                }`}
              >
                {latest.symbol} {latest.side}
              </span>
              <span className="mb-1 font-mono text-xs text-amber">CONF {latest.confidence}%</span>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line/70 pt-3 text-center">
              <div>
                <div className="font-mono text-sm font-semibold text-fg">{latest.tp ?? "—"}</div>
                <div className="font-mono text-[10px] text-muted">TP</div>
              </div>
              <div>
                <div className="font-mono text-sm font-semibold text-fg">{latest.sl ?? "—"}</div>
                <div className="font-mono text-[10px] text-muted">SL</div>
              </div>
              <div>
                <div className="font-mono text-sm font-semibold text-fg">
                  {latest.expected_move != null
                    ? `${latest.expected_move >= 0 ? "+" : ""}${latest.expected_move}%`
                    : "—"}
                </div>
                <div className="font-mono text-[10px] text-muted">EXP MOVE</div>
              </div>
            </div>
          </>
        ) : (
          <p className="mt-2 font-mono text-[11px] text-muted">
            No signals published yet — nothing is writing to the signals table.
          </p>
        )}
      </section>

      <section>
        <SectionTitle title="ALL SIGNALS" meta={loading ? "…" : `${signals.length}`} />
        {loading ? (
          <div className="h-16 animate-pulse rounded-lg border border-line bg-panel" />
        ) : signals.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
            <div className="font-mono text-sm font-semibold text-fg">No signals yet</div>
            <p className="mx-auto mt-1 max-w-[260px] text-[11px] text-muted">
              Signals appear here once an external model (e.g. Kronos) starts publishing
              forecasts to Supabase — see tilly-trading/kronos/.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {signals.map((s) => (
              <div key={s.id} className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center gap-3">
                  <span
                    className={`size-2 shrink-0 rounded-full ${
                      s.side === "BUY" ? "bg-up" : s.side === "SELL" ? "bg-down" : "bg-muted"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-semibold text-fg">{s.symbol}</span>
                      <span
                        className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                          s.side === "BUY"
                            ? "border-up/25 bg-up/15 text-up"
                            : s.side === "SELL"
                              ? "border-down/25 bg-down/15 text-down"
                              : "border-line bg-panel2 text-muted"
                        }`}
                      >
                        {s.side}
                      </span>
                      <span className="font-mono text-[10px] text-amber">CONF {s.confidence}%</span>
                    </div>
                    {s.note && <div className="mt-1 text-[11px] text-muted">{s.note}</div>}
                  </div>
                  <span className="shrink-0 font-mono text-[10px] text-muted">{s.timeframe}</span>
                </div>
                <div className="mt-2 flex items-center justify-between border-t border-line/70 pt-2 font-mono text-[10px] text-muted">
                  <span>{new Date(s.created_at).toLocaleTimeString()}</span>
                  {s.tp != null && <span>TP {s.tp}</span>}
                  {s.sl != null && <span>SL {s.sl}</span>}
                  {s.expected_move != null && (
                    <span className={s.expected_move >= 0 ? "text-up" : "text-down"}>
                      {s.expected_move >= 0 ? "+" : ""}
                      {s.expected_move}%
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
