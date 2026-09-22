"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { useAuth } from "@/components/auth-provider";
import { fetchBrokerAccounts } from "@/lib/db";
import {
  addPaperAccount,
  API_URL,
  brokerApiConfigured,
  linkBroker,
  linkMt5Bridge,
  pingAuthedPost,
  pingBackend,
  pingDB,
} from "@/lib/broker-api";
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
  const [showLink, setShowLink] = useState(false);
  const [showBridge, setShowBridge] = useState(false);
  const [paperBusy, setPaperBusy] = useState(false);
  const admin = isAdmin(user);

  const loadAccounts = useCallback(async () => {
    setLoading(true);
    try {
      setAccounts(await fetchBrokerAccounts());
    } finally {
      setLoading(false);
    }
  }, []);

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
    loadAccounts();
  }, [loadAccounts]);

  // While an account is still provisioning, poll every 5s for the result.
  useEffect(() => {
    if (accounts.some((a) => a.status === "provisioning")) {
      const t = setTimeout(loadAccounts, 5000);
      return () => clearTimeout(t);
    }
  }, [accounts, loadAccounts]);

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
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-mono text-xs tracking-widest text-muted">MY BROKER ACCOUNTS</h2>
          <div className="flex gap-2">
            <button
              onClick={async () => {
                setPaperBusy(true);
                try {
                  await addPaperAccount();
                  await loadAccounts();
                } catch (e) {
                  alert(e instanceof Error ? e.message : "Failed to add paper account");
                } finally {
                  setPaperBusy(false);
                }
              }}
              disabled={paperBusy}
              className="rounded border border-up/40 bg-up/10 px-2 py-1 font-mono text-[10px] font-semibold text-up disabled:opacity-50"
            >
              {paperBusy ? "…" : "+ PAPER"}
            </button>
            <button
              onClick={() => setShowLink((v) => !v)}
              className="rounded border border-amber/40 bg-amber/10 px-2 py-1 font-mono text-[10px] font-semibold text-amber"
            >
              {showLink ? "CLOSE" : "+ LINK"}
            </button>
            <button
              onClick={() => setShowBridge((v) => !v)}
              className="rounded border border-amber/40 bg-amber/10 px-2 py-1 font-mono text-[10px] font-semibold text-amber"
            >
              {showBridge ? "CLOSE" : "+ BRIDGE"}
            </button>
          </div>
        </div>

        {showLink && (
          <LinkBrokerForm
            onDone={() => {
              setShowLink(false);
              loadAccounts();
            }}
          />
        )}

        {showBridge && (
          <BridgeLinkForm
            onDone={() => {
              setShowBridge(false);
              loadAccounts();
            }}
          />
        )}

        {loading ? (
          <div className="h-16 animate-pulse rounded-lg border border-line bg-panel" />
        ) : accounts.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
            <div className="font-mono text-sm font-semibold text-fg">No accounts linked</div>
            <p className="mx-auto mt-1 max-w-[260px] text-[11px] text-muted">
              Link an Exness / XM / Vantage MetaTrader account to trade.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {accounts.map((a) => (
              <div key={a.id} className="rounded-lg border border-line bg-panel p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`size-2 rounded-full ${statusDot(a.status, a.is_active)}`} />
                    <span className="font-mono text-sm font-semibold text-fg">
                      {a.broker_name.toUpperCase()}
                    </span>
                    <span className="rounded border border-line bg-panel2 px-1.5 py-0.5 font-mono text-[10px] text-amber">
                      {a.account_type.toUpperCase()}
                    </span>
                    {a.connection_provider === "self_hosted" && (
                      <span className="rounded border border-line bg-panel2 px-1.5 py-0.5 font-mono text-[10px] text-muted">
                        MT5 BRIDGE
                      </span>
                    )}
                  </div>
                  <span className="font-mono text-xs text-fg">
                    {a.balance != null ? `$${Number(a.balance).toLocaleString()}` : "—"}
                  </span>
                </div>
                <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-muted">
                  <span>LOGIN {a.account_id}</span>
                  <span className="uppercase">{a.status ?? (a.is_active ? "connected" : "—")}</span>
                </div>
                {a.last_error && (
                  <div className="mt-1 truncate font-mono text-[10px] text-down">{a.last_error}</div>
                )}
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

function statusDot(status: string | null, active: boolean): string {
  if (status === "connected" || active) return "bg-up";
  if (status === "error") return "bg-down";
  if (status === "provisioning") return "bg-amber pulse-dot";
  return "bg-muted";
}

function LinkBrokerForm({ onDone }: { onDone: () => void }) {
  const [broker, setBroker] = useState("exness");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [server, setServer] = useState("");
  const [platform, setPlatform] = useState<"mt4" | "mt5">("mt5");
  const [accountType, setAccountType] = useState<"demo" | "live">("demo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ping, setPing] = useState<string | null>(null);

  if (!brokerApiConfigured) {
    return (
      <div className="mb-2 rounded-lg border border-amber/30 bg-amber/10 p-3 font-mono text-[11px] text-amber">
        Backend not connected yet. Set NEXT_PUBLIC_API_URL (your deployed Tilly API) in Cloudflare
        Pages, then reload to link a broker.
      </div>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await linkBroker({
        broker_name: broker,
        login,
        password,
        server,
        platform,
        account_type: accountType,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Linking failed.");
      setBusy(false);
    }
  }

  const field =
    "h-9 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none placeholder:text-muted/50 focus:border-amber/60";

  return (
    <form onSubmit={submit} className="mb-2 space-y-2 rounded-lg border border-line bg-panel p-3">
      <div className="rounded-md border border-line bg-ink p-2">
        <div className="font-mono text-[9px] tracking-widest text-muted">API</div>
        <div className="break-all font-mono text-[10px] text-fg">{API_URL || "(not set)"}</div>
        <div className="mt-1 flex gap-2">
          <button
            type="button"
            onClick={async () => {
              setPing("testing…");
              setPing(await pingBackend());
            }}
            className="rounded border border-line bg-panel2 px-2 py-1 font-mono text-[10px] text-amber"
          >
            Test GET
          </button>
          <button
            type="button"
            onClick={async () => {
              setPing("testing…");
              setPing(await pingAuthedPost());
            }}
            className="rounded border border-line bg-panel2 px-2 py-1 font-mono text-[10px] text-amber"
          >
            Test authed POST
          </button>
          <button
            type="button"
            onClick={async () => {
              setPing("testing…");
              setPing(await pingDB());
            }}
            className="rounded border border-line bg-panel2 px-2 py-1 font-mono text-[10px] text-amber"
          >
            Test DB
          </button>
        </div>
        {ping && <div className="mt-1 break-all font-mono text-[10px] text-up">{ping}</div>}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <select value={broker} onChange={(e) => setBroker(e.target.value)} className={field}>
          <option value="exness">Exness</option>
          <option value="xm">XM</option>
          <option value="vantage">Vantage</option>
        </select>
        <select
          value={accountType}
          onChange={(e) => setAccountType(e.target.value as "demo" | "live")}
          className={field}
        >
          <option value="demo">Demo</option>
          <option value="live">Live</option>
        </select>
      </div>
      <input className={field} placeholder="Login (account number)" value={login} onChange={(e) => setLogin(e.target.value)} />
      <input className={field} type="password" placeholder="Investor / master password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <input className={field} placeholder="Server (e.g. Exness-MT5Real8)" value={server} onChange={(e) => setServer(e.target.value)} />
      <div className="grid grid-cols-2 gap-1 rounded-lg border border-line bg-panel2 p-1">
        {(["mt5", "mt4"] as const).map((p) => (
          <button
            type="button"
            key={p}
            onClick={() => setPlatform(p)}
            className={`rounded-md py-1.5 font-mono text-[10px] uppercase ${
              platform === p ? "bg-amber font-semibold text-ink" : "text-muted"
            }`}
          >
            {p}
          </button>
        ))}
      </div>
      {error && (
        <p className="rounded-md border border-down/30 bg-down/10 px-3 py-2 font-mono text-[10px] text-down">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy}
        className="h-9 w-full rounded-lg bg-amber font-mono text-[11px] font-semibold text-ink transition active:scale-[0.98] disabled:opacity-50"
      >
        {busy ? "Linking…" : "Link account"}
      </button>
    </form>
  );
}

function BridgeLinkForm({ onDone }: { onDone: () => void }) {
  const [broker, setBroker] = useState("exness");
  const [bridgeUrl, setBridgeUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [accountType, setAccountType] = useState<"demo" | "live">("demo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!brokerApiConfigured) {
    return (
      <div className="mb-2 rounded-lg border border-amber/30 bg-amber/10 p-3 font-mono text-[11px] text-amber">
        Backend not connected yet. Set NEXT_PUBLIC_API_URL (your deployed Tilly API) in Cloudflare
        Pages, then reload to link an MT5 bridge.
      </div>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await linkMt5Bridge({
        broker_name: broker,
        bridge_url: bridgeUrl.trim(),
        bridge_api_key: apiKey.trim(),
        account_type: accountType,
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Linking failed.");
      setBusy(false);
    }
  }

  const field =
    "h-9 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none placeholder:text-muted/50 focus:border-amber/60";

  return (
    <form onSubmit={submit} className="mb-2 space-y-2 rounded-lg border border-line bg-panel p-3">
      <p className="font-mono text-[10px] leading-relaxed text-muted">
        Connect a real MT5 account through your own bridge service instead of MetaAPI. Run it next
        to a real MT5 terminal on your own machine — see tilly-trading/mt5-bridge/README.md — then
        paste its HTTPS URL and API key below. We verify it live before saving.
      </p>
      <div className="grid grid-cols-2 gap-2">
        <select value={broker} onChange={(e) => setBroker(e.target.value)} className={field}>
          <option value="exness">Exness</option>
          <option value="xm">XM</option>
          <option value="vantage">Vantage</option>
        </select>
        <select
          value={accountType}
          onChange={(e) => setAccountType(e.target.value as "demo" | "live")}
          className={field}
        >
          <option value="demo">Demo</option>
          <option value="live">Live</option>
        </select>
      </div>
      <input
        className={field}
        placeholder="https://your-bridge.trycloudflare.com"
        value={bridgeUrl}
        onChange={(e) => setBridgeUrl(e.target.value)}
      />
      <input
        className={field}
        type="password"
        placeholder="Bridge API key"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
      />
      {error && (
        <p className="rounded-md border border-down/30 bg-down/10 px-3 py-2 font-mono text-[10px] text-down">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || !bridgeUrl || !apiKey}
        className="h-9 w-full rounded-lg bg-amber font-mono text-[11px] font-semibold text-ink transition active:scale-[0.98] disabled:opacity-50"
      >
        {busy ? "Connecting…" : "Connect bridge"}
      </button>
    </form>
  );
}
