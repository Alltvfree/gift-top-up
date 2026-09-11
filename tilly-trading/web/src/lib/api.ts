/**
 * Typed API client for the Tilly Trading backend.
 *
 * Unlike the original Lovable prototype (mock data only), this talks to the
 * real FastAPI backend. `NEXT_PUBLIC_API_URL` points at it; endpoints that
 * are still stubbed on the backend (auth, bots) return 501 until Tasks 2 & 4.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

const API_V1 = `${API_URL}/api/v1`;

let accessToken: string | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`${API_V1}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ---- Types (mirror backend Pydantic schemas) ----
export interface Preset {
  name: string;
  risk_level: number;
  default_parameters: Record<string, unknown>;
}

export interface Quote {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  source: string;
  ts: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserOut {
  id: string;
  email: string;
  full_name: string | null;
  subscription_tier: string;
  created_at: string;
}

export interface Bot {
  id: string;
  name: string;
  strategy: "GRID" | "DCA";
  symbol: string;
  status: "stopped" | "running" | "paused" | "error";
  parameters: Record<string, unknown>;
  ai_preset_used: string | null;
  total_pnl: number;
  created_at: string;
  started_at: string | null;
  stopped_at: string | null;
}

// ---- Endpoints ----
export const api = {
  health: () => fetch(`${API_URL}/health`).then((r) => r.json()),

  auth: {
    register: (body: { email: string; password: string; full_name?: string }) =>
      request<TokenPair>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
    // OAuth2 password flow expects form-encoded username/password.
    login: async (email: string, password: string) => {
      const form = new URLSearchParams({ username: email, password });
      const res = await fetch(`${API_V1}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form,
      });
      if (!res.ok) throw new ApiError(res.status, "Login failed");
      return (await res.json()) as TokenPair;
    },
    me: () => request<UserOut>("/auth/me"),
  },

  bots: {
    list: () => request<Bot[]>("/bots"),
    create: (body: {
      name: string;
      strategy: "GRID" | "DCA";
      symbol: string;
      parameters?: Record<string, unknown>;
      ai_preset_used?: string;
    }) => request<Bot>("/bots", { method: "POST", body: JSON.stringify(body) }),
    get: (id: string) => request<Bot>(`/bots/${id}`),
    start: (id: string) => request<Bot>(`/bots/${id}/start`, { method: "POST" }),
    stop: (id: string) => request<Bot>(`/bots/${id}/stop`, { method: "POST" }),
    remove: (id: string) => request<void>(`/bots/${id}`, { method: "DELETE" }),
  },

  presets: {
    list: () => request<Preset[]>("/ai-presets"),
    generate: (body: {
      preset: "conservative" | "balanced" | "aggressive";
      strategy: "GRID" | "DCA";
      balance: number;
      symbol: string;
      atr: number;
    }) =>
      request<{ preset: string; strategy: string; parameters: Record<string, unknown> }>(
        "/ai-presets/generate",
        { method: "POST", body: JSON.stringify(body) },
      ),
  },

  market: {
    symbols: () => request<{ symbols: string[] }>("/market/symbols"),
    price: (symbol: string) => request<Quote>(`/market/price/${symbol}`),
    // Live tick stream over WebSocket.
    stream: (symbol: string) =>
      new WebSocket(`${API_URL.replace(/^http/, "ws")}/api/v1/market/ws/${symbol}`),
  },
};
