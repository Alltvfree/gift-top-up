"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { useAuth } from "@/components/auth-provider";
import { fetchBrokerAccounts } from "@/lib/db";
import { displayName, isAdmin } from "@/lib/roles";
import type { BrokerAccountRow } from "@/lib/supabase";

export default function AccountPage() {
  return (
    <ConsoleShell>
      <Account />
    </ConsoleShell>
  );
}

function Account() {
  const { user, signOut, changePassword } = useAuth();
  const [accounts, setAccounts] = useState<BrokerAccountRow[]>([]);
  const [loading, setLoading] = useState(true);
  const admin = isAdmin(user);

  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwMsg(null);
    if (pw.length < 6) {
      setPwMsg({ ok: false, text: "Password must be at least 6 characters." });
      return;
    }
    if (pw !== pw2) {
      setPwMsg({ ok: false, text: "Passwords do not match." });
      return;
    }
    setPwBusy(true);
    const { error } = await changePassword(pw);
    setPwBusy(false);
    if (error) setPwMsg({ ok: false, text: error });
    else {
      setPwMsg({ ok: true, text: "Password updated." });
      setPw("");
      setPw2("");
    }
  }

  useEffect(() => {
    fetchBrokerAccounts()
      .then(setAccounts)
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <h1 className="font-mono text-xs tracking-widest text-muted">MY ACCOUNT</h1>

      <section className="rounded-xl border border-line bg-gradient-to-b from-panel2 to-panel p-4">
        <div className="flex items-center gap-3">
          <div className="grid size-12 place-items-center rounded-lg bg-amber text-lg font-bold text-ink">
            {displayName(user).slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="truncate text-base font-semibold text-fg">{displayName(user)}</div>
            <div className="truncate font-mono text-[11px] text-muted">{user?.email}</div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 border-t border-line/70 pt-3">
          <Meta label="PLAN" value="Free" />
          <Meta label="ROLE" value={admin ? "Admin" : "Trader"} />
        </div>
        <button
          onClick={() => signOut()}
          className="mt-3 h-10 w-full rounded-lg border border-down/30 bg-down/10 font-mono text-[11px] font-semibold text-down transition active:scale-[0.98]"
        >
          SIGN OUT
        </button>
      </section>

      {admin && (
        <Link
          href="/admin"
          className="flex items-center justify-between rounded-xl border border-amber/30 bg-amber/10 p-4 transition active:scale-[0.99]"
        >
          <div>
            <div className="text-sm font-semibold text-amber">Admin panel</div>
            <div className="font-mono text-[10px] text-muted">System health · platform controls</div>
          </div>
          <span className="text-amber">→</span>
        </Link>
      )}

      <section className="rounded-xl border border-line bg-panel p-4">
        <SectionTitle title="CHANGE PASSWORD" />
        <form onSubmit={handleChangePassword} className="space-y-2.5">
          <input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            placeholder="New password"
            className="h-10 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none placeholder:text-muted/50 focus:border-amber/60"
          />
          <input
            type="password"
            value={pw2}
            onChange={(e) => setPw2(e.target.value)}
            placeholder="Confirm new password"
            className="h-10 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none placeholder:text-muted/50 focus:border-amber/60"
          />
          {pwMsg && (
            <p
              className={`rounded-md border px-3 py-2 font-mono text-[11px] ${
                pwMsg.ok
                  ? "border-up/30 bg-up/10 text-up"
                  : "border-down/30 bg-down/10 text-down"
              }`}
            >
              {pwMsg.text}
            </p>
          )}
          <button
            type="submit"
            disabled={pwBusy}
            className="h-10 w-full rounded-lg bg-amber font-mono text-[12px] font-semibold text-ink transition active:scale-[0.98] disabled:opacity-50"
          >
            {pwBusy ? "Updating…" : "Update password"}
          </button>
        </form>
      </section>

      <section>
        <SectionTitle
          title="MY BROKER ACCOUNTS"
          meta={loading ? "…" : `${accounts.length} LINKED`}
        />
        {loading ? (
          <div className="h-16 animate-pulse rounded-lg border border-line bg-panel" />
        ) : accounts.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
            <div className="font-mono text-sm font-semibold text-fg">No accounts linked</div>
            <p className="mx-auto mt-1 max-w-[260px] text-[11px] text-muted">
              Link an Exness / XM / Vantage account via MetaAPI to trade (Task 3).
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {accounts.map((a) => (
              <div key={a.id} className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`size-2 rounded-full ${a.is_active ? "bg-up" : "bg-muted"}`} />
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
    </>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-2.5 text-center">
      <div className="font-mono text-sm font-semibold text-fg">{value}</div>
      <div className="mt-0.5 font-mono text-[10px] tracking-wide text-muted">{label}</div>
    </div>
  );
}
