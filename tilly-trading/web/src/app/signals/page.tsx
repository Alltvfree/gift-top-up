import type { Metadata } from "next";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { signals } from "@/lib/mock-data";

export const metadata: Metadata = {
  title: "Signals — Tilly Trading Console",
  description: "Forecast signals for XAUUSD with confidence, timeframe, take-profit and stop-loss levels.",
};

export default function Signals() {
  return (
    <ConsoleShell>
      <h1 className="font-mono text-xs tracking-widest text-muted">SIGNAL FEED · XAU/USD</h1>

      <section className="rounded-xl border border-line bg-gradient-to-b from-panel2 to-panel p-4">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] tracking-widest text-muted">FORECAST BIAS</span>
          <span className="font-mono text-[11px] text-amber">M15 · TILLY-AI</span>
        </div>
        <div className="mt-2 flex items-end gap-2">
          <span className="font-mono text-[34px] font-semibold leading-none tracking-tight text-fg">
            +0.42%
          </span>
          <span className="mb-1.5 font-mono text-xs text-up">CONF 84%</span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line/70 pt-3 text-center">
          <div>
            <div className="font-mono text-sm font-semibold text-fg">H1</div>
            <div className="font-mono text-[10px] text-muted">REGIME</div>
          </div>
          <div>
            <div className="font-mono text-sm font-semibold text-amber">6</div>
            <div className="font-mono text-[10px] text-muted">HORIZON</div>
          </div>
          <div>
            <div className="font-mono text-sm font-semibold text-up">1:2.3</div>
            <div className="font-mono text-[10px] text-muted">R:R</div>
          </div>
        </div>
      </section>

      <section>
        <SectionTitle title="ALL SIGNALS" meta={`${signals.length} TODAY`} />
        <div className="space-y-2">
          {signals.map((s) => (
            <div key={s.id} className="rounded-lg border border-line bg-panel p-3">
              <div className="flex items-center gap-3">
                <span
                  className={`size-2 shrink-0 rounded-full ${s.side === "BUY" ? "bg-up" : "bg-down"} ${
                    s.live ? "pulse-dot" : ""
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-fg">{s.symbol}</span>
                    <span
                      className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                        s.side === "BUY"
                          ? "border-up/25 bg-up/15 text-up"
                          : "border-down/25 bg-down/15 text-down"
                      }`}
                    >
                      {s.side}
                    </span>
                    <span className="font-mono text-[10px] text-amber">CONF {s.confidence}%</span>
                  </div>
                  <div className="mt-1 text-[11px] text-muted">{s.note}</div>
                </div>
                <span className="shrink-0 font-mono text-[10px] text-muted">{s.timeframe}</span>
              </div>
              <div className="mt-2 flex items-center justify-between border-t border-line/70 pt-2 font-mono text-[10px] text-muted">
                <span>{s.time}</span>
                <span>TP {s.tp}</span>
                <span>SL {s.sl}</span>
                <span className={s.move >= 0 ? "text-up" : "text-down"}>
                  {s.move >= 0 ? "+" : "−"}
                  {Math.abs(s.move)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </ConsoleShell>
  );
}
