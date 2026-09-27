"""Per-symbol contract specifications.

BTCUSDm and XAUUSDm do NOT share point size, contract size, or lot limits —
copy-pasting one symbol's numbers onto another is the same class of mistake
as the earlier TP/SL-in-raw-dollars bug (see README), just at the execution
layer instead of the labeling layer. These defaults are reasonable
approximations for a typical Exness-style `m`-suffixed account and are
clearly marked as such — override them from real MT5 data
(`mt5.symbol_info(symbol)`) when running on the VPS, via `from_mt5()`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    point: float  # smallest price increment (e.g. 0.01 for XAUUSD, 0.01 for BTCUSD on a 2-digit quote)
    digits: int
    contract_size: float  # units of the base asset per 1.0 lot
    volume_min: float
    volume_max: float
    volume_step: float
    tick_size: float  # smallest price move that changes value (often == point)
    tick_value: float  # account-currency value of one tick move for 1.0 lot
    currency: str = "USD"
    default_spread_points: float = 20.0  # used only when no historical spread column is available

    def round_volume(self, lots: float) -> float:
        if lots <= 0:
            return 0.0
        steps = round(lots / self.volume_step)
        lots = steps * self.volume_step
        return max(self.volume_min, min(self.volume_max, lots))

    def points_to_price(self, points: float) -> float:
        return points * self.point

    def pnl_per_point(self, lots: float) -> float:
        """Account-currency P&L for a 1-point move at the given lot size."""
        return lots * (self.tick_value / self.tick_size) * self.point if self.tick_size else 0.0


# Defaults only — real specs should come from MT5's symbol_info() on the VPS
# where a live terminal is available (see from_mt5 below).
KNOWN_SYMBOLS: dict[str, SymbolSpec] = {
    "XAUUSDM": SymbolSpec(
        symbol="XAUUSDm",
        point=0.01,
        digits=2,
        contract_size=100.0,  # 1 lot = 100 oz
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        tick_size=0.01,
        tick_value=1.0,  # $1 per 0.01 move per 1.0 lot on a 100oz contract
        default_spread_points=20.0,
    ),
    "BTCUSDM": SymbolSpec(
        symbol="BTCUSDm",
        point=0.01,
        digits=2,
        contract_size=1.0,  # 1 lot = 1 BTC
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        tick_size=0.01,
        tick_value=0.01,  # $0.01 per 0.01 move per 1.0 lot on a 1-BTC contract
        default_spread_points=3000.0,  # BTC quotes in points are large; this is ~$30 at point=0.01
    ),
}


def get_symbol_spec(symbol: str) -> SymbolSpec:
    spec = KNOWN_SYMBOLS.get(symbol.upper())
    if spec is None:
        raise ValueError(
            f"No SymbolSpec for {symbol!r}. Known: {sorted(KNOWN_SYMBOLS)}. "
            "Add one to backtest/symbols.py, or pass --spec-from-mt5 to import "
            "it from a live MT5 terminal via from_mt5()."
        )
    return SymbolSpec(**{**spec.__dict__, "symbol": symbol})


def from_mt5(symbol: str) -> SymbolSpec:
    """Import the real contract spec from a live MT5 terminal. Only works on
    the Windows VPS with a logged-in terminal — same constraint as
    mt5_data.py. Falls back is the caller's job (get_symbol_spec)."""
    import MetaTrader5 as mt5  # noqa: PLC0415 - Windows-only, imported lazily

    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"MT5 symbol_info({symbol!r}) returned None — is it in Market Watch?")
    return SymbolSpec(
        symbol=symbol,
        point=info.point,
        digits=info.digits,
        contract_size=info.trade_contract_size,
        volume_min=info.volume_min,
        volume_max=info.volume_max,
        volume_step=info.volume_step,
        tick_size=info.trade_tick_size,
        tick_value=info.trade_tick_value,
        currency=info.currency_profit,
        default_spread_points=float(info.spread),
    )
