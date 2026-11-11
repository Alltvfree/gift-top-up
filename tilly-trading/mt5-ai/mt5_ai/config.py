"""Settings, all from environment variables so nothing sensitive or personal
lives in code. Defaults are deliberately conservative: demo accounts only,
gold only, one open position, small risk."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # Orders are refused on a real-money account unless this is switched on
    # by the person, in their own environment. Claude cannot change it.
    allow_live: bool = False
    symbols: tuple[str, ...] = ("XAUUSD*",)  # fnmatch patterns, case-insensitive
    max_risk_pct: float = 1.0
    max_daily_loss_pct: float = 3.0
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    max_lot: float = 1.0
    min_rr: float = 1.5
    max_spread_to_stop: float = 0.2     # spread may be at most 20% of the stop distance
    max_drift_to_stop: float = 0.25     # price may move at most 25% of the stop distance between ticket and order
    deviation_points: int = 30
    ticket_ttl_seconds: int = 300
    magic: int = 26110001               # tags every order this server sends
    state_dir: Path = Path.home() / ".mt5-ai"
    kronos_repo: str | None = None      # folder holding Kronos' `model` package (shiyu-coder/Kronos)
    kronos_dir: str | None = None       # tilly-trading/kronos on the PC (features.py, setups/, config/)
    kronos_model: str = "mini"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Settings":
        e = os.environ if env is None else env
        d = cls()

        def num(name, default, cast):
            raw = e.get(name)
            return cast(raw) if raw not in (None, "") else default

        symbols = tuple(s.strip() for s in e.get("MT5_AI_SYMBOLS", "").split(",") if s.strip()) or d.symbols
        s = cls(
            allow_live=_flag(e.get("MT5_AI_ALLOW_LIVE")),
            symbols=symbols,
            max_risk_pct=num("MT5_AI_MAX_RISK_PCT", d.max_risk_pct, float),
            max_daily_loss_pct=num("MT5_AI_MAX_DAILY_LOSS_PCT", d.max_daily_loss_pct, float),
            max_trades_per_day=num("MT5_AI_MAX_TRADES_PER_DAY", d.max_trades_per_day, int),
            max_open_positions=num("MT5_AI_MAX_OPEN_POSITIONS", d.max_open_positions, int),
            max_lot=num("MT5_AI_MAX_LOT", d.max_lot, float),
            min_rr=num("MT5_AI_MIN_RR", d.min_rr, float),
            max_spread_to_stop=num("MT5_AI_MAX_SPREAD_TO_STOP", d.max_spread_to_stop, float),
            max_drift_to_stop=num("MT5_AI_MAX_DRIFT_TO_STOP", d.max_drift_to_stop, float),
            deviation_points=num("MT5_AI_DEVIATION_POINTS", d.deviation_points, int),
            ticket_ttl_seconds=num("MT5_AI_TICKET_TTL_SECONDS", d.ticket_ttl_seconds, int),
            magic=num("MT5_AI_MAGIC", d.magic, int),
            state_dir=Path(e.get("MT5_AI_STATE_DIR") or d.state_dir),
            kronos_repo=e.get("MT5_AI_KRONOS_REPO") or None,
            kronos_dir=e.get("MT5_AI_KRONOS_DIR") or None,
            kronos_model=e.get("MT5_AI_KRONOS_MODEL") or d.kronos_model,
        )
        s.validate()
        return s

    def validate(self) -> None:
        if not 0 < self.max_risk_pct <= 100 or self.max_daily_loss_pct <= 0:
            raise ValueError("max_risk_pct and max_daily_loss_pct must be positive percentages.")
        if self.max_trades_per_day < 1 or self.max_open_positions < 1 or self.max_lot <= 0:
            raise ValueError("max_trades_per_day, max_open_positions and max_lot must be positive.")
        if self.min_rr <= 0 or self.ticket_ttl_seconds < 1:
            raise ValueError("min_rr and ticket_ttl_seconds must be positive.")
