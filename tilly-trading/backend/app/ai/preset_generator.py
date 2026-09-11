"""AI preset generator.

Generates optimal bot parameters based on:
    - user's risk profile (conservative / balanced / aggressive)
    - account balance
    - symbol volatility (ATR)
    - market regime (trending / ranging)  [phase 2]
"""
from __future__ import annotations

from typing import Any


class AIPresetGenerator:
    PRESETS: dict[str, dict[str, Any]] = {
        "conservative": {
            "risk_multiplier": 0.5,
            "max_drawdown_pct": 5,
            "grid_levels": 5,
            "lot_per_1000": 0.01,
            "risk_level": 2,
        },
        "balanced": {
            "risk_multiplier": 1.0,
            "max_drawdown_pct": 10,
            "grid_levels": 10,
            "lot_per_1000": 0.02,
            "risk_level": 5,
        },
        "aggressive": {
            "risk_multiplier": 2.0,
            "max_drawdown_pct": 20,
            "grid_levels": 15,
            "lot_per_1000": 0.05,
            "risk_level": 9,
        },
    }

    def generate_grid_params(
        self, preset: str, balance: float, symbol: str, atr: float
    ) -> dict[str, Any]:
        config = self.PRESETS[preset]

        # Lot size scales with balance and the preset's risk appetite.
        lot_size = (balance / 1000) * config["lot_per_1000"] * config["risk_multiplier"]

        # Grid geometry from volatility (ATR).
        grid_spacing = atr * 0.5      # half-ATR between levels
        grid_range = atr * 3          # +/- 3 ATR around current price

        return {
            "strategy": "GRID",
            "symbol": symbol,
            "grid_levels": config["grid_levels"],
            "grid_spacing": round(grid_spacing, 5),
            "grid_range": round(grid_range, 5),
            "lot_size": round(lot_size, 2),
            "take_profit_pips": round(grid_spacing * 10000, 1),
            "stop_loss_pct": config["max_drawdown_pct"],
        }

    def generate_dca_params(
        self, preset: str, balance: float, symbol: str, atr: float
    ) -> dict[str, Any]:
        config = self.PRESETS[preset]
        base_lot = (balance / 1000) * config["lot_per_1000"] * config["risk_multiplier"] * 0.5

        return {
            "strategy": "DCA",
            "symbol": symbol,
            "base_lot": round(base_lot, 2),
            "multiplier": 1.5,
            "max_orders": 6,
            "deviation_pips": round(atr * 10000 * 0.3, 1),
            "take_profit_pips": round(atr * 10000 * 0.5, 1),
            "stop_loss_pct": config["max_drawdown_pct"],
        }

    def generate(
        self, preset: str, strategy: str, balance: float, symbol: str, atr: float
    ) -> dict[str, Any]:
        if strategy.upper() == "DCA":
            return self.generate_dca_params(preset, balance, symbol, atr)
        return self.generate_grid_params(preset, balance, symbol, atr)
