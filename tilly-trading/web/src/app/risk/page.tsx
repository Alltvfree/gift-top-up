"use client";

import { useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { account, riskEvents, riskSettings } from "@/lib/mock-data";

export default function Risk() {
  const [halted, setHalted] = useState(false);
  const [armed, setArmed] = useState(false);

  return (
    <ConsoleShell>
      <h1 className="font-mono text-xs tracking-widest text-muted">RISK CONTROL</h1>

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

      <section>
        <SectionTitle title="LIMITS" meta="ENFORCED" />
        <div className="grid grid-cols-2 gap-2">
          {riskSettings.map((r) => (
            <div key={r.label} className="rounded-lg border border-line bg-panel p-3">
              <div className="font-mono text-[10px] tracking-wide text-muted">{r.label}</div>
              <div className="mt-1 font-mono text-sm font-semibold text-fg">{r.value}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <SectionTitle title="GUARD EVENTS" meta={`${riskEvents.length} TODAY`} />
        <div className="space-y-2">
          {riskEvents.map((e) => (
            <div key={e.id} className="flex items-start gap-3 rounded-lg border border-line bg-panel p-3">
              <span
                className={`rounded border px-1.5 py-0.5 font-mono text-[10px] ${
                  e.level === "WARN"
                    ? "border-amber/30 bg-amber/10 text-amber"
                    : "border-line bg-panel2 text-muted"
                }`}
              >
                {e.level}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[11px] text-fg">{e.text}</div>
                <div className="mt-1 font-mono text-[10px] text-muted">{e.time}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-down/30 bg-panel p-3.5">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-[13px] font-semibold text-down">Emergency Stop</div>
            <div className="font-mono text-[10px] text-muted">Flatten all · halt signals</div>
          </div>
          <span className="pulse-dot size-2.5 rounded-full bg-down" />
        </div>
        <label className="mt-3 flex items-center gap-2 font-mono text-[10px] text-muted">
          <input
            type="checkbox"
            checked={armed}
            onChange={(e) => setArmed(e.target.checked)}
            className="size-3.5 accent-[#fb5d5d]"
          />
          ARM SWITCH
        </label>
        <button
          disabled={!armed}
          onClick={() => setHalted(true)}
          className="mt-2 h-12 w-full rounded-lg bg-down font-mono text-[12px] font-bold tracking-widest text-ink transition active:scale-[0.98] disabled:opacity-35"
        >
          {halted ? "/// BOT HALTED ///" : "/// TRIGGER KILL SWITCH ///"}
        </button>
        {halted ? (
          <p className="mt-2 font-mono text-[10px] text-down">
            Halt requested · all strategies suspended
          </p>
        ) : null}
      </section>
    </ConsoleShell>
  );
}
