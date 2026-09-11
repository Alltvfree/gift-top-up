"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/components/auth-provider";
import { LoginScreen } from "@/components/login-screen";

const NAV = [
  { to: "/", glyph: "▣", label: "Home" },
  { to: "/signals", glyph: "◈", label: "Signals" },
  { to: "/trades", glyph: "⇄", label: "Trades" },
  { to: "/risk", glyph: "⚙", label: "Risk" },
  { to: "/account", glyph: "◉", label: "Account" },
] as const;

function initials(email?: string | null) {
  if (!email) return "TT";
  const name = email.split("@")[0];
  return name.slice(0, 2).toUpperCase();
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { session, loading, user } = useAuth();

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-ink">
        <div className="font-mono text-xs tracking-widest text-muted">LOADING…</div>
      </div>
    );
  }

  if (!session) return <LoginScreen />;

  return (
    <div className="min-h-screen bg-ink text-fg">
      <header className="sticky top-0 z-10 border-b border-line/70 bg-ink/95">
        <div className="mx-auto flex h-14 max-w-[390px] items-center justify-between px-4">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="grid size-8 place-items-center rounded-md bg-amber text-sm font-bold text-ink">
              T
            </div>
            <div className="leading-none">
              <div className="font-semibold tracking-tight text-fg">TILLY</div>
              <div className="mt-0.5 font-mono text-[10px] tracking-widest text-muted">
                TRADING CONSOLE
              </div>
            </div>
          </Link>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded-full border border-up/25 bg-up/10 px-2.5 py-1 font-mono text-[10px] text-up">
              <span className="tick-live size-1.5 rounded-full bg-up" /> LIVE
            </span>
            <div
              title={user?.email ?? undefined}
              className="grid size-8 place-items-center rounded-md border border-line bg-panel text-xs font-semibold text-amber"
            >
              {initials(user?.email)}
            </div>
          </div>
        </div>
        <div className="h-0.5 overflow-hidden bg-panel">
          <div className="sweep h-full w-1/3 bg-gradient-to-r from-transparent via-amber to-transparent" />
        </div>
      </header>

      <main className="mx-auto max-w-[390px] space-y-4 px-4 pb-28 pt-4">{children}</main>

      <nav className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-surface">
        <div className="mx-auto grid h-16 max-w-[390px] grid-cols-5">
          {NAV.map((item) => {
            const active = pathname === item.to;
            return (
              <Link
                key={item.to}
                href={item.to}
                className={`flex flex-col items-center justify-center gap-1 ${
                  active ? "text-amber" : "text-muted"
                }`}
              >
                <span className="text-base leading-none">{item.glyph}</span>
                <span className="font-mono text-[10px]">{item.label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}

export function SectionTitle({ title, meta }: { title: string; meta?: string }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h2 className="font-mono text-xs tracking-widest text-muted">{title}</h2>
      {meta ? <span className="font-mono text-[10px] text-amber">{meta}</span> : null}
    </div>
  );
}
