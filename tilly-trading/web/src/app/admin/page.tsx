"use client";

import { useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { accounts, auditLog, systemHealth } from "@/lib/mock-data";

const MODES = ["BACKTEST", "PAPER", "LIVE"] as const;

export default function Admin() {
  const [mode, setMode] = useState<(typeof MODES)[number]>("LIVE");

  return (
    <ConsoleShell>
      <h1 className="font-mono text-xs tracking-widest text-muted">ADMIN · GRID-07</h1>

      <section className="rounded-xl border border-line bg-panel p-3.5">
        <div className="mb-2.5 font-mono text-xs tracking-widest text-muted">STRATEGY MODE</div>
        <div className="grid grid-cols-3 gap-1 rounded-lg border border-line bg-panel2 p-1">
          {MODES.map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md py-2 font-mono text-[10px] tracking-wide ${
                mode === m ? "bg-amber font-semibold text-ink" : "text-muted"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between font-mono text-[10px] text-muted">
          <span>
            MIN CONF <span className="text-fg">75%</span>
          </span>
          <span>
            MAX DD <span className="text-fg">6%</span>
          </span>
          <span>
            LOT <span className="text-fg">0.50</span>
          </span>
        </div>
      </section>

      <section>
        <SectionTitle title="BROKER ACCOUNTS" meta={`${accounts.length} LINKED`} />
        <div className="space-y-2">
          {accounts.map((a) => (
            <div key={a.id} className="rounded-lg border border-line bg-panel p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`size-2 rounded-full ${a.status === "connected" ? "bg-up" : "bg-muted"}`}
                  />
                  <span className="font-mono text-sm font-semibold text-fg">{a.broker}</span>
                  <span className="rounded border border-line bg-panel2 px-1.5 py-0.5 font-mono text-[10px] text-amber">
                    {a.mode}
                  </span>
                </div>
                <span className="font-mono text-xs text-fg">${a.equity.toLocaleString()}</span>
              </div>
              <div className="mt-2 font-mono text-[10px] text-muted">
                LOGIN {a.login} · {a.status.toUpperCase()}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <SectionTitle title="SYSTEM HEALTH" />
        <div className="grid grid-cols-2 gap-2">
          {systemHealth.map((h) => (
            <div key={h.label} className="rounded-lg border border-line bg-panel p-3">
              <div className="font-mono text-[10px] tracking-wide text-muted">{h.label}</div>
              <div className={`mt-1 font-mono text-sm font-semibold ${h.ok ? "text-up" : "text-down"}`}>
                {h.value}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <SectionTitle title="AUDIT LOG" />
        <div className="overflow-hidden rounded-lg border border-line bg-panel">
          {auditLog.map((l) => (
            <div
              key={l.id}
              className="flex items-start gap-3 border-b border-line/60 px-3 py-2.5 last:border-0"
            >
              <span className="font-mono text-[10px] text-muted">{l.time}</span>
              <span className="font-mono text-[10px] text-amber">{l.actor}</span>
              <span className="min-w-0 flex-1 text-[11px] text-fg">{l.text}</span>
            </div>
          ))}
        </div>
      </section>
    </ConsoleShell>
  );
}
