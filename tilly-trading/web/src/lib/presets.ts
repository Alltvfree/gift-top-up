/**
 * AI preset parameter generator — TypeScript port of the backend
 * AIPresetGenerator, so "Generate with AI" works client-side against Supabase.
 */
export type PresetName = "conservative" | "balanced" | "aggressive";
export type Strategy = "GRID" | "DCA";

interface PresetConfig {
  risk_multiplier: number;
  max_drawdown_pct: number;
  grid_levels: number;
  lot_per_1000: number;
  risk_level: number;
}

export const PRESETS: Record<PresetName, PresetConfig> = {
  conservative: { risk_multiplier: 0.5, max_drawdown_pct: 5, grid_levels: 5, lot_per_1000: 0.01, risk_level: 2 },
  balanced: { risk_multiplier: 1.0, max_drawdown_pct: 10, grid_levels: 10, lot_per_1000: 0.02, risk_level: 5 },
  aggressive: { risk_multiplier: 2.0, max_drawdown_pct: 20, grid_levels: 15, lot_per_1000: 0.05, risk_level: 9 },
};

const round = (n: number, dp: number) => Number(n.toFixed(dp));

export function generateParams(
  preset: PresetName,
  strategy: Strategy,
  balance: number,
  symbol: string,
  atr: number,
): Record<string, number | string> {
  const c = PRESETS[preset];

  if (strategy === "DCA") {
    const baseLot = (balance / 1000) * c.lot_per_1000 * c.risk_multiplier * 0.5;
    return {
      strategy: "DCA",
      symbol,
      base_lot: round(baseLot, 2),
      multiplier: 1.5,
      max_orders: 6,
      deviation_pips: round(atr * 10000 * 0.3, 1),
      take_profit_pips: round(atr * 10000 * 0.5, 1),
      stop_loss_pct: c.max_drawdown_pct,
    };
  }

  const lotSize = (balance / 1000) * c.lot_per_1000 * c.risk_multiplier;
  const gridSpacing = atr * 0.5;
  return {
    strategy: "GRID",
    symbol,
    grid_levels: c.grid_levels,
    grid_spacing: round(gridSpacing, 5),
    grid_range: round(atr * 3, 5),
    lot_size: round(lotSize, 2),
    take_profit_pips: round(gridSpacing * 10000, 1),
    stop_loss_pct: c.max_drawdown_pct,
  };
}
