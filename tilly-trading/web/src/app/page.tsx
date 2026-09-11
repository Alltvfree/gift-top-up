import Link from "next/link";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { account, positions, signals } from "@/lib/mock-data";

export default function Deck() {
  return (
    <ConsoleShell>
      <h1 className="sr-only">XAUUSD trading bot deck</h1>

      <section className="rounded-xl border border-line bg-gradient-to-b from-panel2 to-panel p-4">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] tracking-widest text-muted">NET LIQUIDITY</span>
          <span className="font-mono text-[11px] text-amber">{account.model}</span>
        </div>
        <div className="mt-2 flex items-end gap-2">
          <span className="font-mono text-[34px] font-semibold leading-none tracking-tight text-fg">
            ${account.netLiquidity.toLocaleString()}
          </span>
          <span className="mb-1.5 font-mono text-xs text-up">▲ {account.changePct}%</span>
        </div>
        <div className="mt-3 flex h-9 items-end gap-1">
          {account.equityCurve.map((h, i) => (
            <div
              key={i}
              className="flex-1 bg-amber"
              style={{ height: `${h}%`, opacity: 0.5 + i * 0.05 }}
            />
          ))}
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line/70 pt-3 text-center">
          <div>
            <div className="font-mono text-sm font-semibold text-fg">
              {String(account.openTrades).padStart(2, "0")}
            </div>
            <div className="font-mono text-[10px] tracking-wide text-muted">OPEN</div>
          </div>
          <div>
            <div className="font-mono text-sm font-semibold text-up">
              +${account.dayPnl.toLocaleString()}
            </div>
            <div className="font-mono text-[10px] tracking-wide text-muted">P&amp;L</div>
          </div>
          <div>
            <div className="font-mono text-sm font-semibold text-amber">{account.riskPct}%</div>
            <div className="font-mono text-[10px] tracking-wide text-muted">RISK</div>
          </div>
        </div>
      </section>

      <section>
        <SectionTitle title="LIVE SIGNALS" meta={`${signals.filter((s) => s.live).length} ACTIVE`} />
        <div className="space-y-2">
          {signals.slice(0, 3).map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-3 rounded-lg border border-line bg-panel p-3"
            >
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
                <div className="mt-1 text-[11px] text-muted">
                  {s.note} · TP {s.tp} · SL {s.sl}
                </div>
              </div>
              <span className={`shrink-0 font-mono text-xs ${s.move >= 0 ? "text-up" : "text-down"}`}>
                {s.move >= 0 ? "+" : "−"}
                {Math.abs(s.move)}%
              </span>
            </div>
          ))}
        </div>
      </section>

      <section>
        <SectionTitle title="OPEN POSITIONS" meta={`${positions.length} OF 07`} />
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
                <span>MARKET {p.market}</span>
                <span>TP {p.tp}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel p-3.5">
        <div className="mb-2.5 flex items-center justify-between">
          <h2 className="font-mono text-xs tracking-widest text-muted">RISK EXPOSURE</h2>
          <span className="font-mono text-[11px] text-amber">{account.riskPct}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-ink">
          <div
            className="h-full rounded-full bg-gradient-to-r from-amber2 to-amber"
            style={{ width: `${account.riskPct}%` }}
          />
        </div>
        <div className="mt-2 flex justify-between font-mono text-[10px] text-muted">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-2">
        <Link
          href="/signals"
          className="grid h-12 place-items-center rounded-lg bg-amber text-sm font-semibold text-ink transition active:scale-[0.98]"
        >
          New Order
        </Link>
        <Link
          href="/admin"
          className="grid h-12 place-items-center rounded-lg border border-line bg-panel text-sm font-medium text-fg transition active:scale-[0.98]"
        >
          Backtest
        </Link>
      </section>
    </ConsoleShell>
  );
}
