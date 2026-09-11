"use client";

import { useEffect, useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { fetchPositions } from "@/lib/db";
import type { PositionRow } from "@/lib/supabase";

export default function TradesPage() {
  return (
    <ConsoleShell>
      <Trades />
    </ConsoleShell>
  );
}

function Trades() {
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchPositions()
      .then(setPositions)
      .finally(() => setLoading(false));
  }, []);

  const openPnl = positions.reduce((a, p) => a + Number(p.unrealized_pnl ?? 0), 0);

  return (
    <>
      <h1 className="font-mono text-xs tracking-widest text-muted">TRADE BLOTTER</h1>

      <section className="grid grid-cols-3 gap-2">
        <Stat label="OPEN" value={String(positions.length)} tone="text-fg" />
        <Stat
          label="OPEN P&L"
          value={`${openPnl >= 0 ? "+" : "−"}$${Math.abs(openPnl)}`}
          tone={openPnl >= 0 ? "text-up" : "text-down"}
        />
        <Stat label="CLOSED" value="—" tone="text-muted" />
      </section>

      <section>
        <SectionTitle title="OPEN POSITIONS" meta={loading ? "…" : `${positions.length}`} />
        {loading ? (
          <div className="h-16 animate-pulse rounded-lg border border-line bg-panel" />
        ) : positions.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
            <div className="font-mono text-sm font-semibold text-fg">No open positions</div>
            <p className="mx-auto mt-1 max-w-[260px] text-[11px] text-muted">
              A running bot opens positions once broker execution is wired (Task 4).
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {positions.map((p) => (
              <div key={p.id} className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                        p.side.toUpperCase().startsWith("B") || p.side.toUpperCase() === "LONG"
                          ? "border-up/25 bg-up/15 text-up"
                          : "border-down/25 bg-down/15 text-down"
                      }`}
                    >
                      {p.side}
                    </span>
                    <span className="font-mono text-sm font-semibold text-fg">{p.symbol}</span>
                    <span className="font-mono text-[10px] text-muted">{p.volume}</span>
                  </div>
                  <span
                    className={`font-mono text-xs ${
                      Number(p.unrealized_pnl) >= 0 ? "text-up" : "text-down"
                    }`}
                  >
                    {Number(p.unrealized_pnl) >= 0 ? "+" : "−"}$
                    {Math.abs(Number(p.unrealized_pnl))}
                  </span>
                </div>
                <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-muted">
                  <span>ENTRY {p.open_price}</span>
                  <span>MKT {p.current_price ?? "—"}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionTitle title="CLOSED TRADES" />
        <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
          <p className="text-[11px] text-muted">
            Trade history will populate as bots close positions.
          </p>
        </div>
      </section>
    </>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-3 text-center">
      <div className={`font-mono text-sm font-semibold ${tone}`}>{value}</div>
      <div className="mt-1 font-mono text-[10px] tracking-wide text-muted">{label}</div>
    </div>
  );
}
