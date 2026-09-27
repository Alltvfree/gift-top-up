"""Backtest configuration — everything the spec (see kronos/README.md's
"Phase 3" section) says must not be hardcoded: walk-forward window sizes,
signal thresholds, risk/position-sizing mode, spread/slippage/commission
model, TP/SL, and execution convention. Loaded from TOML
(config/backtest.toml) with CLI flags able to override individual fields —
see backtest/__main__.py.

TOML, not YAML: `tomllib` is in the standard library from Python 3.11
onward — nothing to `pip install`, ever, on any machine. PyYAML was tried
first and failed the same way matplotlib did (see charts.py's docstring):
no prebuilt wheel yet for a brand-new CPython release, and no C compiler on
the VPS to build one from source. TOML still supports `#` comments, so the
config files stay just as human-editable as the YAML they replaced.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path


@dataclass
class WalkForwardConfig:
    train_days: int = 90
    validation_days: int = 14
    test_days: int = 14
    step_days: int = 14
    embargo_minutes: int = 60


@dataclass
class SignalConfig:
    buy_threshold: float = 0.60
    sell_threshold: float = 0.40
    cooldown_bars: int = 3
    max_positions: int = 1


@dataclass
class RiskConfig:
    # mode: "fixed_lot" | "fixed_money" | "percent_equity"
    mode: str = "percent_equity"
    risk_percent: float = 1.0
    fixed_money: float = 10.0
    fixed_lot: float = 0.01
    max_lot: float = 5.0


@dataclass
class StopLossConfig:
    # type: "points" | "price"
    type: str = "points"
    value: float = 200.0


@dataclass
class TakeProfitConfig:
    type: str = "points"
    value: float = 300.0


@dataclass
class SpreadConfig:
    # mode: "historical" (use the symbol's own recorded `spread` column from
    # MT5 — preferred, it's real data) | "fixed" (points) | "percentage"
    mode: str = "historical"
    points: float = 20.0
    percent: float = 0.02


@dataclass
class SlippageConfig:
    # mode: "fixed_points" | "random"
    mode: str = "fixed_points"
    points: float = 2.0
    random_std_points: float = 1.0


@dataclass
class CommissionConfig:
    # type: "per_lot" | "percentage" | "fixed_per_trade"
    type: str = "per_lot"
    value: float = 3.5


@dataclass
class ExecutionConfig:
    # Signal is generated from bar T's close (features computed from data
    # through and including bar T). next_bar=True means the trade is
    # entered at bar T+1's open — the realistic, no-lookahead convention.
    # False would enter at bar T's own close, matching how labels.py scores
    # training outcomes but NOT something a live system could actually do
    # (you can't trade a candle's close the instant it prints and also have
    # already used that candle's own high/low to compute your features).
    next_bar: bool = True
    same_bar_exit_policy: str = "conservative"  # "conservative" | "optimistic" | "random"
    max_holding_bars: int = 50


@dataclass
class BacktestConfig:
    symbol: str = "BTCUSDm"
    timeframe: str = "M5"
    higher_timeframe: str | None = "H1"
    initial_balance: float = 10_000.0
    currency: str = "USD"
    side: str = "BUY"  # which label direction the model was/will be trained for
    random_seed: int = 42

    walk_forward: WalkForwardConfig = field(default_factory=WalkForwardConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    stop_loss: StopLossConfig = field(default_factory=StopLossConfig)
    take_profit: TakeProfitConfig = field(default_factory=TakeProfitConfig)
    spread: SpreadConfig = field(default_factory=SpreadConfig)
    slippage: SlippageConfig = field(default_factory=SlippageConfig)
    commission: CommissionConfig = field(default_factory=CommissionConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)


_SECTION_TYPES = {
    "walk_forward": WalkForwardConfig,
    "signal": SignalConfig,
    "risk": RiskConfig,
    "stop_loss": StopLossConfig,
    "take_profit": TakeProfitConfig,
    "spread": SpreadConfig,
    "slippage": SlippageConfig,
    "commission": CommissionConfig,
    "execution": ExecutionConfig,
}


def load_config(path: str | Path | None) -> BacktestConfig:
    """Load a BacktestConfig from TOML. Missing sections/fields fall back to
    the dataclass defaults above — a partial config file is valid, it just
    means "use the default for anything I didn't mention." No file at all
    (path=None) returns pure defaults, useful for --quick smoke runs."""
    raw: dict = {}
    if path is not None:
        with open(path, "rb") as f:
            raw = tomllib.load(f) or {}

    top_level = {k: v for k, v in raw.items() if k not in _SECTION_TYPES}
    cfg = BacktestConfig(**{k: v for k, v in top_level.items() if k in _field_names(BacktestConfig)})

    for section, cls in _SECTION_TYPES.items():
        if section in raw and raw[section] is not None:
            section_data = {k: v for k, v in raw[section].items() if k in _field_names(cls)}
            setattr(cfg, section, cls(**section_data))
    return cfg


def _field_names(dc: type) -> set[str]:
    return {f.name for f in fields(dc)}


def config_to_dict(cfg: BacktestConfig) -> dict:
    """Plain-dict form for saving into a report (reproducibility — Phase 26).
    Never include secrets: this config has none by construction (no
    credentials belong in a BacktestConfig), but this stays a pure
    dataclass->dict walk so nothing else can sneak in either."""

    def _walk(obj):
        if is_dataclass(obj):
            return {f.name: _walk(getattr(obj, f.name)) for f in fields(obj)}
        return obj

    return _walk(cfg)
