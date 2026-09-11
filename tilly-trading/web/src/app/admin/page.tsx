"use client";

import { useEffect, useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { useAuth } from "@/components/auth-provider";
import { fetchBrokerAccounts } from "@/lib/db";
import type { BrokerAccountRow } from "@/lib/supabase";

const systemHealth = [
  { label: "SUPABASE DB", value: "OK", ok: true },
  { label: "AUTH", value: "OK", ok: true },
  { label: "RLS", value: "ENFORCED", ok: true },
  { label: "BROKER BRIDGE", value: "TASK 3", ok: false },
];

export default function AdminPage() {
  return (
    <ConsoleShell>
      <Admin />
    </ConsoleShell>
  );
}

function Admin() {
  const { user, signOut } = useAuth();
  const [accounts, setAccounts] = useState<BrokerAccountRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchBrokerAccounts()
      .then(setAccounts)
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <h1 className="font-mono text-xs tracking-widest text-muted">ADMIN</h1>

      <section className="rounded-xl border border-line bg-panel p-4">
        <div className="mb-2 font-mono text-[10px] tracking-widest text-muted">SIGNED IN AS</div>
        <div className="font-mono text-sm text-fg">{user?.email}</div>
        <button
          onClick={() => signOut()}
          className="mt-3 h-9 w-full rounded-lg border border-down/30 bg-down/10 font-mono text-[11px] font-semibold text-down transition active:scale-[0.98]"
        >
          SIGN OUT
        </button>
      </section>

      <section>
        <SectionTitle
          title="BROKER ACCOUNTS"
          meta={loading ? "…" : `${accounts.length} LINKED`}
        />
        {loading ? (
          <div className="h-16 animate-pulse rounded-lg border border-line bg-panel" />
        ) : accounts.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
            <div className="font-mono text-sm font-semibold text-fg">No accounts linked</div>
            <p className="mx-auto mt-1 max-w-[260px] text-[11px] text-muted">
              MetaAPI account linking (Exness / XM / Vantage) arrives in Task 3.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {accounts.map((a) => (
              <div key={a.id} className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`size-2 rounded-full ${a.is_active ? "bg-up" : "bg-muted"}`}
                    />
                    <span className="font-mono text-sm font-semibold text-fg">
                      {a.broker_name.toUpperCase()}
                    </span>
                    <span className="rounded border border-line bg-panel2 px-1.5 py-0.5 font-mono text-[10px] text-amber">
                      {a.account_type.toUpperCase()}
                    </span>
                  </div>
                  <span className="font-mono text-xs text-fg">
                    {a.balance != null ? `$${Number(a.balance).toLocaleString()}` : "—"}
                  </span>
                </div>
                <div className="mt-2 font-mono text-[10px] text-muted">LOGIN {a.account_id}</div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <SectionTitle title="SYSTEM HEALTH" />
        <div className="grid grid-cols-2 gap-2">
          {systemHealth.map((h) => (
            <div key={h.label} className="rounded-lg border border-line bg-panel p-3">
              <div className="font-mono text-[10px] tracking-wide text-muted">{h.label}</div>
              <div
                className={`mt-1 font-mono text-sm font-semibold ${h.ok ? "text-up" : "text-amber"}`}
              >
                {h.value}
              </div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
