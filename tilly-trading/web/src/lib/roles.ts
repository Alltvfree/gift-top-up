import type { User } from "@supabase/supabase-js";

/**
 * Admins are identified by either:
 *   - a `role: "admin"` claim in Supabase app_metadata / user_metadata, or
 *   - their email being in NEXT_PUBLIC_ADMIN_EMAILS (comma-separated).
 *
 * This gates page *visibility*. Sensitive data is still protected by RLS in
 * Supabase — for privileged writes you'd add an admin RLS policy keyed off the
 * same role claim.
 */
const ADMIN_EMAILS = (
  process.env.NEXT_PUBLIC_ADMIN_EMAILS || "mohamed.shuhail96@gmail.com"
)
  .split(",")
  .map((s) => s.trim().toLowerCase())
  .filter(Boolean);

export function isAdmin(user: User | null): boolean {
  if (!user) return false;
  const role =
    (user.app_metadata as Record<string, unknown>)?.role ??
    (user.user_metadata as Record<string, unknown>)?.role;
  if (role === "admin") return true;
  const email = user.email?.toLowerCase();
  return !!email && ADMIN_EMAILS.includes(email);
}

export function displayName(user: User | null): string {
  if (!user) return "";
  const full = (user.user_metadata as Record<string, unknown>)?.full_name;
  if (typeof full === "string" && full.trim()) return full;
  return user.email?.split("@")[0] ?? "Trader";
}
