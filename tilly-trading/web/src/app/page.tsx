"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { fetchBots, fetchPositions, setBotStatus } from "@/lib/db";
import type { BotRow, PositionRow } from "@/lib/supabase";

export default function Deck() {
  return (
    <ConsoleShell>
      <Dashboard />
    </ConsoleShell>
  );
}

function Dashboard() {
  const [bots, setBots] = useState<BotRow[]>([]);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [b, p] = await Promise.all([fetchBots(), fetchPositions()]);
      setBots(b);
      setPositions(p);
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    // Live refresh every 5s (silent = no skeleton flicker) so balance/P&L and
    // positions update while bots run, without a manual reload.
    const t = setInterval(() => load(true), 5000);
    const onVisible = () => {
      if (document.visibilityState === "visible") load(true);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  async function toggle(bot: BotRow) {
    setBusyId(bot.id);
    try {
      await setBotStatus(bot.id, bot.status === "running" ? "stopped" : "running");
      await load();
    } finally {
      setBusyId(null);
    }
  }

  const running = bots.filter((b) => b.status === "running").length;
  const totalPnl = bots.reduce((a, b) => a + Number(b.total_pnl ?? 0), 0);

  return (
    <>
      <h1 className="sr-only">Trading bot deck</h1>

      <section className="rounded-xl border border-line bg-gradient-to-b from-panel2 to-panel p-4">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[11px] tracking-widest text-muted">TOTAL P&amp;L</span>
          <span className="font-mono text-[11px] text-amber">LIVE · SUPABASE</span>
        </div>
        <div className="mt-2 flex items-end gap-2">
          <span
            className={`font-mono text-[34px] font-semibold leading-none tracking-tight ${
              totalPnl >= 0 ? "text-fg" : "text-down"
            }`}
          >
            {totalPnl >= 0 ? "+" : "−"}${Math.abs(totalPnl).toLocaleString()}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line/70 pt-3 text-center">
          <Stat value={String(bots.length).padStart(2, "0")} label="BOTS" tone="text-fg" />
          <Stat value={String(running).padStart(2, "0")} label="RUNNING" tone="text-up" />
          <Stat value={String(positions.length).padStart(2, "0")} label="OPEN" tone="text-amber" />
        </div>
      </section>

      <section>
        <SectionTitle title="YOUR BOTS" meta={loading ? "…" : `${bots.length} TOTAL`} />
        {loading ? (
          <SkeletonCard />
        ) : bots.length === 0 ? (
          <EmptyState
            title="No bots yet"
            body="Create your first GRID or DCA bot to get started."
            cta={{ href: "/bots/new", label: "Create a bot" }}
          />
        ) : (
          <div className="space-y-2">
            {bots.map((b) => (
              <div key={b.id} className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`size-2 shrink-0 rounded-full ${
                        b.status === "running" ? "bg-up pulse-dot" : "bg-muted"
                      }`}
                    />
                    <span className="font-mono text-sm font-semibold text-fg">{b.name}</span>
                    <span className="rounded border border-line bg-panel2 px-1.5 py-0.5 font-mono text-[10px] text-amber">
                      {b.strategy}
                    </span>
                    <span className="font-mono text-[10px] text-muted">{b.symbol}</span>
                  </div>
                  <span
                    className={`font-mono text-xs ${
                      Number(b.total_pnl) >= 0 ? "text-up" : "text-down"
                    }`}
                  >
                    {Number(b.total_pnl) >= 0 ? "+" : "−"}${Math.abs(Number(b.total_pnl))}
                  </span>
                </div>
                {b.status === "error" && b.last_error && (
                  <div className="mt-2 break-words font-mono text-[10px] text-down">
                    {b.last_error}
                  </div>
                )}
                <div className="mt-3 flex items-center justify-between">
                  <span className="font-mono text-[10px] uppercase text-muted">{b.status}</span>
                  <button
                    disabled={busyId === b.id}
                    onClick={() => toggle(b)}
                    className={`h-8 rounded-lg px-4 font-mono text-[11px] font-semibold transition active:scale-[0.98] disabled:opacity-50 ${
                      b.status === "running"
                        ? "border border-line bg-panel2 text-fg"
                        : "bg-amber text-ink"
                    }`}
                  >
                    {busyId === b.id ? "…" : b.status === "running" ? "STOP" : "START"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionTitle title="OPEN POSITIONS" meta={`${positions.length}`} />
        {positions.length === 0 ? (
          <EmptyState
            title="No open positions"
            body="Positions appear here once a running bot opens trades (Task 4: broker execution)."
          />
        ) : (
          <div className="space-y-2">
            {positions.map((p) => (
              <div key={p.id} className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-fg">{p.symbol}</span>
                    <span className="font-mono text-[10px] text-muted">{p.side}</span>
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
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="grid grid-cols-2 gap-2">
        <Link
          href="/bots/new"
          className="grid h-12 place-items-center rounded-lg bg-amber text-sm font-semibold text-ink transition active:scale-[0.98]"
        >
          + New Bot
        </Link>
        <Link
          href="/account"
          className="grid h-12 place-items-center rounded-lg border border-line bg-panel text-sm font-medium text-fg transition active:scale-[0.98]"
        >
          Account
        </Link>
      </section>
    </>
  );
}

function Stat({ value, label, tone }: { value: string; label: string; tone: string }) {
  return (
    <div>
      <div className={`font-mono text-sm font-semibold ${tone}`}>{value}</div>
      <div className="font-mono text-[10px] tracking-wide text-muted">{label}</div>
    </div>
  );
}

function SkeletonCard() {
  return <div className="h-16 animate-pulse rounded-lg border border-line bg-panel" />;
}

function EmptyState({
  title,
  body,
  cta,
}: {
  title: string;
  body: string;
  cta?: { href: string; label: string };
}) {
  return (
    <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
      <div className="font-mono text-sm font-semibold text-fg">{title}</div>
      <p className="mx-auto mt-1 max-w-[260px] text-[11px] text-muted">{body}</p>
      {cta && (
        <Link
          href={cta.href}
          className="mt-3 inline-grid h-9 place-items-center rounded-lg bg-amber px-4 text-[12px] font-semibold text-ink"
        >
          {cta.label}
        </Link>
      )}
    </div>
  );
}
