"use client";

import Link from "next/link";
import { ConsoleShell, SectionTitle } from "@/components/console-shell";
import { useAuth } from "@/components/auth-provider";
import { isAdmin } from "@/lib/roles";

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
  const { user } = useAuth();

  if (!isAdmin(user)) {
    return (
      <>
        <h1 className="font-mono text-xs tracking-widest text-muted">ADMIN</h1>
        <div className="rounded-xl border border-down/30 bg-down/10 p-6 text-center">
          <div className="text-sm font-semibold text-down">Restricted</div>
          <p className="mx-auto mt-1 max-w-[260px] text-[11px] text-muted">
            The admin panel is only available to administrators. You&apos;re signed in as a
            trader.
          </p>
          <Link
            href="/account"
            className="mt-4 inline-grid h-9 place-items-center rounded-lg border border-line bg-panel px-4 font-mono text-[11px] text-fg"
          >
            ← Back to my account
          </Link>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="flex items-center justify-between">
        <h1 className="font-mono text-xs tracking-widest text-muted">ADMIN PANEL</h1>
        <span className="rounded border border-amber/30 bg-amber/10 px-1.5 py-0.5 font-mono text-[10px] text-amber">
          ADMIN
        </span>
      </div>

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

      <section>
        <SectionTitle title="PLATFORM" />
        <div className="rounded-lg border border-dashed border-line bg-panel/50 p-5 text-center">
          <p className="text-[11px] text-muted">
            User management, global strategy controls and audit log arrive with the bot runner
            (Task 4). Admin-only writes will be enforced by a Supabase RLS policy on the same
            role claim.
          </p>
        </div>
      </section>

      <Link
        href="/account"
        className="inline-grid h-10 w-full place-items-center rounded-lg border border-line bg-panel font-mono text-[11px] text-fg transition active:scale-[0.98]"
      >
        ← Back to my account
      </Link>
    </>
  );
}
