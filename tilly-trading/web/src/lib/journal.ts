/**
 * Feeds Tilly's own trade history into @luxalgo/journal-core (MIT, pure
 * functions, no IO) for the win rate / profit factor / drawdown / Edge Score
 * analytics on the Trades page.
 *
 * We skip journal-core's Execution -> buildRoundTrips step entirely: GRID and
 * DCA bots never partial-fill a single position, so each `positions` row
 * already IS a flat-to-flat round trip (one open, one close), not a raw fill.
 * `positionsToRoundTrips` below maps that row shape straight onto
 * journal-core's `RoundTrip` type.
 *
 * Caveat carried through to the UI: the backend doesn't get an exact close
 * fill price back from the broker interface, so a closed position's
 * `realized_pnl` is its last-known unrealized P&L the tick before it closed
 * (see backend/app/services/engine.py::_sync_positions) — a same-tick
 * approximation, not a booked exit price.
 */
import type { PositionRow } from "@/lib/supabase";
import type { RoundTrip } from "@luxalgo/journal-core";

export function positionsToRoundTrips(positions: PositionRow[]): RoundTrip[] {
  return positions.map((p) => {
    const isOpen = p.closed_at === null;
    const netPnl = isOpen ? p.unrealized_pnl : p.realized_pnl;
    const status: RoundTrip["status"] = isOpen
      ? "open"
      : Math.abs(netPnl) < 0.005
        ? "breakeven"
        : netPnl > 0
          ? "win"
          : "loss";

    return {
      key: p.id,
      accountId: p.bot_id,
      symbol: p.symbol,
      assetClass: "forex",
      direction: p.side.toUpperCase() === "SELL" ? "short" : "long",
      status,
      openedAt: p.opened_at,
      closedAt: p.closed_at ?? undefined,
      quantity: p.volume,
      openQuantity: isOpen ? p.volume : 0,
      avgEntry: p.open_price,
      avgExit: isOpen ? undefined : (p.current_price ?? p.open_price),
      grossPnl: netPnl,
      fees: 0,
      netPnl,
      executionCount: 1,
      executionIds: [p.id],
      exits: isOpen ? [] : [{ executionId: p.id, grossPnl: netPnl, quantity: p.volume }],
      durationMs:
        !isOpen && p.closed_at
          ? Date.parse(p.closed_at) - Date.parse(p.opened_at)
          : undefined,
    };
  });
}
