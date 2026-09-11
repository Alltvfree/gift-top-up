/**
 * Client for the Tilly backend broker API (Task 3).
 *
 * Broker linking needs the server-side MetaAPI token, so it can't run in the
 * browser — it calls the deployed FastAPI backend, authenticated with the
 * user's Supabase access token. Set NEXT_PUBLIC_API_URL to the backend URL.
 */
import { supabase } from "@/lib/supabase";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
export const brokerApiConfigured = API_URL.length > 0;

/** Diagnostic: GET the backend /health from the browser (exercises CORS too). */
export async function pingBackend(): Promise<string> {
  if (!brokerApiConfigured) return "NEXT_PUBLIC_API_URL not set";
  try {
    const res = await fetch(`${API_URL}/health`, { method: "GET" });
    const body = await res.text();
    return `GET ${res.status} · ${body.slice(0, 120)}`;
  } catch (e) {
    return `GET failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

/** Diagnostic: authenticated POST (same auth+CORS path as linking, but instant). */
export async function pingAuthedPost(): Promise<string> {
  if (!brokerApiConfigured) return "NEXT_PUBLIC_API_URL not set";
  try {
    const res = await fetch(`${API_URL}/api/v1/broker/ping`, {
      method: "POST",
      headers: await authHeaders(),
      body: JSON.stringify({}),
    });
    const body = await res.text();
    return `POST ${res.status} · ${body.slice(0, 160)}`;
  } catch (e) {
    return `POST failed: ${e instanceof Error ? e.message : String(e)}`;
  }
}

export interface LinkBrokerInput {
  broker_name: string;
  login: string;
  password: string;
  server: string;
  platform: "mt4" | "mt5";
  account_type: "demo" | "live";
}

async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

export async function linkBroker(input: LinkBrokerInput): Promise<void> {
  if (!brokerApiConfigured) {
    throw new Error("Backend not configured (NEXT_PUBLIC_API_URL is not set).");
  }
  const res = await fetch(`${API_URL}/api/v1/broker/link`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
}
