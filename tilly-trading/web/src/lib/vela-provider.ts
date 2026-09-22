/**
 * Vela chart DataProvider backed by Tilly's own simulated market-data
 * endpoint (`/api/v1/market/candles/{symbol}`, see backend/app/api/v1/market.py).
 *
 * Implements just the required `getBars` method — Vela's own polling handles
 * live updates for us (see docs/contributing/adding-a-data-provider.md:
 * "Absent `subscribe` ⇒ the feed polls `getBars` for live ticks instead").
 */
import { API_URL, brokerApiConfigured } from "@/lib/broker-api";

export interface VelaBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface VelaBarRange {
  from?: number;
  to?: number;
  limit?: number;
}

export const tillyMarketProvider = {
  async getBars(ticker: string, timeframe: string, range: VelaBarRange): Promise<VelaBar[]> {
    if (!brokerApiConfigured) return [];
    const limit = Math.min(Math.max(range.limit ?? 200, 1), 1000);
    const qs = new URLSearchParams({ timeframe, limit: String(limit) });
    try {
      const res = await fetch(`${API_URL}/api/v1/market/candles/${encodeURIComponent(ticker)}?${qs}`);
      if (!res.ok) return [];
      const body: { bars?: VelaBar[] } = await res.json();
      return Array.isArray(body.bars) ? body.bars : [];
    } catch {
      return [];
    }
  },
};
