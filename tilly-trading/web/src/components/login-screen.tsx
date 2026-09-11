"use client";

import { useState } from "react";
import { useAuth } from "@/components/auth-provider";

export function LoginScreen() {
  const { signIn, signUp } = useAuth();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    if (mode === "login") {
      const { error } = await signIn(email, password);
      if (error) setError(error);
    } else {
      const { error, needsConfirmation } = await signUp(email, password, fullName);
      if (error) setError(error);
      else if (needsConfirmation)
        setNotice("Account created. Check your email to confirm, then sign in.");
    }
    setBusy(false);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink px-4">
      <div className="w-full max-w-[360px]">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="grid size-9 place-items-center rounded-md bg-amber text-base font-bold text-ink">
            T
          </div>
          <div className="leading-none">
            <div className="text-lg font-semibold tracking-tight text-fg">TILLY</div>
            <div className="mt-0.5 font-mono text-[10px] tracking-widest text-muted">
              TRADING CONSOLE
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-line bg-gradient-to-b from-panel2 to-panel p-5">
          <div className="mb-4 grid grid-cols-2 gap-1 rounded-lg border border-line bg-panel2 p-1">
            {(["login", "signup"] as const).map((m) => (
              <button
                key={m}
                onClick={() => {
                  setMode(m);
                  setError(null);
                  setNotice(null);
                }}
                className={`rounded-md py-2 font-mono text-[11px] tracking-wide ${
                  mode === m ? "bg-amber font-semibold text-ink" : "text-muted"
                }`}
              >
                {m === "login" ? "SIGN IN" : "SIGN UP"}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            {mode === "signup" && (
              <Field
                label="FULL NAME"
                value={fullName}
                onChange={setFullName}
                type="text"
                placeholder="Jane Trader"
                required={false}
              />
            )}
            <Field
              label="EMAIL"
              value={email}
              onChange={setEmail}
              type="email"
              placeholder="you@example.com"
            />
            <Field
              label="PASSWORD"
              value={password}
              onChange={setPassword}
              type="password"
              placeholder="••••••••"
            />

            {error && (
              <p className="rounded-md border border-down/30 bg-down/10 px-3 py-2 font-mono text-[11px] text-down">
                {error}
              </p>
            )}
            {notice && (
              <p className="rounded-md border border-up/30 bg-up/10 px-3 py-2 font-mono text-[11px] text-up">
                {notice}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="h-11 w-full rounded-lg bg-amber text-sm font-semibold text-ink transition active:scale-[0.98] disabled:opacity-50"
            >
              {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>

        <p className="mt-4 text-center font-mono text-[10px] text-muted">
          Secured by Supabase Auth · data protected by RLS
        </p>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type,
  placeholder,
  required = true,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type: string;
  placeholder?: string;
  required?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[10px] tracking-widest text-muted">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="h-10 w-full rounded-lg border border-line bg-ink px-3 text-sm text-fg outline-none placeholder:text-muted/50 focus:border-amber/60"
      />
    </label>
  );
}
