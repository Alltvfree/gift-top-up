import type { Metadata } from "next";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { closedTrades, positions } from "@/lib/mock-data";

export const metadata: Metadata = {
  title: "Trades — Tilly Trading Console",
  description: "Open positions with entry, SL and TP plus closed trade history and win rate.",
};

export default function Trades() {
  const net = closedTrades.reduce((a, t) => a + t.pnl, 0);
  const wins = closedTrades.filter((t) => t.pnl > 0).length;

  return (
    <ConsoleShell>
      <h1 className="font-mono text-xs tracking-widest text-muted">TRADE BLOTTER</h1>

      <section className="grid grid-cols-3 gap-2">
        {[
          { label: "NET", value: `${net >= 0 ? "+" : "−"}$${Math.abs(net)}`, tone: "text-up" },
          {
            label: "WIN RATE",
            value: `${Math.round((wins / closedTrades.length) * 100)}%`,
            tone: "text-amber",
          },
          { label: "TRADES", value: String(closedTrades.length), tone: "text-fg" },
        ].map((s) => (
          <div key={s.label} className="rounded-lg border border-line bg-panel p-3 text-center">
            <div className={`font-mono text-sm font-semibold ${s.tone}`}>{s.value}</div>
            <div className="mt-1 font-mono text-[10px] tracking-wide text-muted">{s.label}</div>
          </div>
        ))}
      </section>

      <section>
        <SectionTitle title="OPEN POSITIONS" meta={`${positions.length} OPEN`} />
        <div className="space-y-2">
          {positions.map((p) => (
            <div key={p.id} className="rounded-lg border border-line bg-panel p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                      p.side === "LONG"
                        ? "border-up/25 bg-up/15 text-up"
                        : "border-down/25 bg-down/15 text-down"
                    }`}
                  >
                    {p.side}
                  </span>
                  <span className="font-mono text-sm font-semibold text-fg">{p.symbol}</span>
                  <span className="font-mono text-[10px] text-muted">{p.volume}</span>
                </div>
                <span className={`font-mono text-xs ${p.pnl >= 0 ? "text-up" : "text-down"}`}>
                  {p.pnl >= 0 ? "+" : "−"}${Math.abs(p.pnl)}
                </span>
              </div>
              <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-muted">
                <span>ENTRY {p.entry}</span>
                <span>SL {p.sl}</span>
                <span>TP {p.tp}</span>
              </div>
              <button className="mt-3 h-9 w-full rounded-lg border border-line bg-panel2 font-mono text-[11px] text-fg transition active:scale-[0.98]">
                CLOSE POSITION
              </button>
            </div>
          ))}
        </div>
      </section>

      <section>
        <SectionTitle title="CLOSED TRADES" />
        <div className="overflow-hidden rounded-lg border border-line bg-panel">
          <div className="grid grid-cols-12 gap-2 border-b border-line px-3 py-2 font-mono text-[9px] tracking-wider text-muted">
            <div className="col-span-3">SIDE</div>
            <div className="col-span-2">VOL</div>
            <div className="col-span-4">CLOSED</div>
            <div className="col-span-3 text-right">PNL</div>
          </div>
          {closedTrades.map((t) => (
            <div
              key={t.id}
              className="grid grid-cols-12 items-center gap-2 border-b border-line/60 px-3 py-2.5 font-mono text-[11px] last:border-0"
            >
              <div className={`col-span-3 ${t.side === "LONG" ? "text-up" : "text-down"}`}>
                {t.side}
              </div>
              <div className="col-span-2 text-fg">{t.volume}</div>
              <div className="col-span-4 text-muted">{t.closed}</div>
              <div className={`col-span-3 text-right ${t.pnl >= 0 ? "text-up" : "text-down"}`}>
                {t.pnl >= 0 ? "+" : "−"}${Math.abs(t.pnl)}
              </div>
            </div>
          ))}
        </div>
      </section>
    </ConsoleShell>
  );
}
