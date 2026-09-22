"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { createBot, fetchBrokerAccounts } from "@/lib/db";
import type { BrokerAccountRow } from "@/lib/supabase";
import { generateParams, type PresetName, type Strategy } from "@/lib/presets";

const SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD"];
const PRESETS: PresetName[] = ["conservative", "balanced", "aggressive"];

export default function NewBotPage() {
  return (
    <ConsoleShell>
      <NewBot />
    </ConsoleShell>
  );
}

function NewBot() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [strategy, setStrategy] = useState<Strategy>("GRID");
  const [symbol, setSymbol] = useState("XAUUSD");
  const [preset, setPreset] = useState<PresetName>("balanced");
  const [balance, setBalance] = useState("10000");
  const [atr, setAtr] = useState("2.5");
  const [params, setParams] = useState<Record<string, number | string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<BrokerAccountRow[]>([]);
  const [accountId, setAccountId] = useState<string>("");

  useEffect(() => {
    fetchBrokerAccounts().then((a) => {
      setAccounts(a);
      // Default to the first connected account (e.g. the paper account).
      const connected = a.find((x) => x.status === "connected") ?? a[0];
      if (connected) setAccountId(connected.id);
    });
  }, []);

  function handleGenerate() {
    const b = parseFloat(balance);
    const a = parseFloat(atr);
    if (!b || !a) {
      setError("Enter a valid balance and ATR to generate parameters.");
      return;
    }
    setError(null);
    setParams(generateParams(preset, strategy, b, symbol, a));
  }

  async function handleCreate() {
    if (!name.trim()) {
      setError("Give your bot a name.");
      return;
    }
    if (!accountId) {
      setError("Add a broker account first (Account → + PAPER).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createBot({
        name: name.trim(),
        strategy,
        symbol,
        parameters: params ?? {},
        ai_preset_used: params ? preset : null,
        broker_account_id: accountId,
      });
      router.push("/");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create bot.");
      setBusy(false);
    }
  }

  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="font-mono text-xs tracking-widest text-muted">NEW BOT</h1>
        <Link href="/" className="font-mono text-[10px] text-muted">
          ← Cancel
        </Link>
      </div>

      <section className="space-y-3 rounded-xl border border-line bg-panel p-4">
        <label className="block">
          <span className="mb-1 block font-mono text-[10px] tracking-widest text-muted">NAME</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Gold Grid"
            className="h-10 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none placeholder:text-muted/50 focus:border-amber/60"
          />
        </label>

        <div>
          <span className="mb-1 block font-mono text-[10px] tracking-widest text-muted">
            STRATEGY
          </span>
          <div className="grid grid-cols-2 gap-1 rounded-lg border border-line bg-panel2 p-1">
            {(["GRID", "DCA"] as Strategy[]).map((s) => (
              <button
                key={s}
                onClick={() => {
                  setStrategy(s);
                  setParams(null);
                }}
                className={`rounded-md py-2 font-mono text-[11px] ${
                  strategy === s ? "bg-amber font-semibold text-ink" : "text-muted"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <label className="block">
          <span className="mb-1 block font-mono text-[10px] tracking-widest text-muted">SYMBOL</span>
          <input
            list="symbol-options"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="XAUUSD"
            className="h-10 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none placeholder:text-muted/50 focus:border-amber/60"
          />
          <datalist id="symbol-options">
            {SYMBOLS.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          <p className="mt-1 font-mono text-[9px] text-muted">
            Pick a common symbol or type your broker&apos;s exact name (e.g. XAUUSDm) — real
            brokers often suffix theirs differently.
          </p>
        </label>

        <label className="block">
          <span className="mb-1 block font-mono text-[10px] tracking-widest text-muted">
            BROKER ACCOUNT
          </span>
          {accounts.length === 0 ? (
            <Link
              href="/account"
              className="flex h-10 items-center rounded-lg border border-amber/40 bg-amber/10 px-3 text-[12px] text-amber"
            >
              No account — add one (Account → + PAPER) →
            </Link>
          ) : (
            <select
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
              className="h-10 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none focus:border-amber/60"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.broker_name.toUpperCase()} · {a.account_id} ({a.status ?? "?"})
                </option>
              ))}
            </select>
          )}
        </label>
      </section>

      <section className="space-y-3 rounded-xl border border-line bg-panel p-4">
        <SectionTitle title="AI PRESET" />
        <div className="grid grid-cols-3 gap-1 rounded-lg border border-line bg-panel2 p-1">
          {PRESETS.map((p) => (
            <button
              key={p}
              onClick={() => {
                setPreset(p);
                setParams(null);
              }}
              className={`rounded-md py-2 font-mono text-[10px] capitalize ${
                preset === p ? "bg-amber font-semibold text-ink" : "text-muted"
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="mb-1 block font-mono text-[10px] tracking-widest text-muted">
              BALANCE ($)
            </span>
            <input
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
              inputMode="decimal"
              className="h-10 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none focus:border-amber/60"
            />
          </label>
          <label className="block">
            <span className="mb-1 block font-mono text-[10px] tracking-widest text-muted">ATR</span>
            <input
              value={atr}
              onChange={(e) => setAtr(e.target.value)}
              inputMode="decimal"
              className="h-10 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none focus:border-amber/60"
            />
          </label>
        </div>

        <button
          onClick={handleGenerate}
          className="h-10 w-full rounded-lg border border-amber/40 bg-amber/10 font-mono text-[12px] font-semibold text-amber transition active:scale-[0.98]"
        >
          ✦ Generate with AI
        </button>

        {params && (
          <div className="rounded-lg border border-line bg-ink p-3">
            <div className="mb-2 font-mono text-[10px] tracking-widest text-muted">
              GENERATED PARAMETERS
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
              {Object.entries(params).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="font-mono text-[10px] text-muted">{k}</span>
                  <span className="font-mono text-[11px] text-fg">{String(v)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      {error && (
        <p className="rounded-md border border-down/30 bg-down/10 px-3 py-2 font-mono text-[11px] text-down">
          {error}
        </p>
      )}

      <button
        onClick={handleCreate}
        disabled={busy}
        className="h-12 w-full rounded-lg bg-amber text-sm font-semibold text-ink transition active:scale-[0.98] disabled:opacity-50"
      >
        {busy ? "Creating…" : "Create bot"}
      </button>
    </>
  );
}
