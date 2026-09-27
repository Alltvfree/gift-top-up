"""Walk-forward orchestration (Phases 3, 4, 17) — the piece that turns
train.py's single chronological split into a rolling series of independent
train/validate/freeze/test cycles, then hands each window's frozen-model
test predictions to the trade simulator.

Critical property this file exists to guarantee: each test window's
predictions come from a model trained ONLY on data from before that
window (see leakage_audit.build_audit_table's "Hyperparameter/threshold/
TP/SL tuning" entry). Windows are trained independently and their trades/
predictions are concatenated only AFTER each one is frozen and scored —
never "predict once with the final model over the whole history and
pretend it's walk-forward," which is the exact anti-pattern the project's
own spec for this file called out by name.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # to import train/features/labels as flat modules

from features import compute_features  # noqa: E402
from train import feature_columns_for, prepare_dataset, train_model  # noqa: E402

from .account import Account  # noqa: E402
from .config import BacktestConfig  # noqa: E402
from .leakage_audit import LookaheadError, audit_merge, verify_higher_timeframe_alignment  # noqa: E402
from .metrics import model_metrics, trading_metrics  # noqa: E402
from .simulator import run_simulation, trades_to_frame  # noqa: E402
from .symbols import SymbolSpec  # noqa: E402
from .timeframes import TIMEFRAME_MINUTES, bars_per_year  # noqa: E402
from .windows import Window, generate_windows  # noqa: E402

# Bars of lead-in history prepended before each window's train_start purely
# to warm up indicators (EMA-200 is the slowest one in features.py) — real,
# already-past history, not a leakage concern; see walk_forward.py's own
# module docstring and leakage_audit.build_audit_table.
WARMUP_BARS = 250


@dataclass
class WalkForwardWindowResult:
    window: Window
    train_rows: int
    val_rows: int
    test_rows: int
    model_metrics: dict
    trading_metrics: dict
    skipped_reason: str | None = None


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindowResult] = field(default_factory=list)
    all_trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    overall_model_metrics: dict = field(default_factory=dict)
    overall_trading_metrics: dict = field(default_factory=dict)


def _stop_loss_distance(cfg: BacktestConfig, spec: SymbolSpec) -> float:
    return cfg.stop_loss.value * spec.point if cfg.stop_loss.type == "points" else cfg.stop_loss.value


def _take_profit_distance(cfg: BacktestConfig, spec: SymbolSpec) -> float:
    return cfg.take_profit.value * spec.point if cfg.take_profit.type == "points" else cfg.take_profit.value


def run_walk_forward(
    base_raw: pd.DataFrame,
    cfg: BacktestConfig,
    spec: SymbolSpec,
    higher_raw: pd.DataFrame | None = None,
    lgb_params: dict | None = None,
) -> WalkForwardResult:
    base_minutes = TIMEFRAME_MINUTES.get(cfg.timeframe.upper())
    if base_minutes is None:
        raise ValueError(f"Unknown timeframe {cfg.timeframe!r}")

    data_start, data_end = base_raw["time"].iloc[0], base_raw["time"].iloc[-1]
    windows = generate_windows(
        data_start, data_end,
        cfg.walk_forward.train_days, cfg.walk_forward.validation_days,
        cfg.walk_forward.test_days, cfg.walk_forward.step_days,
        cfg.walk_forward.embargo_minutes,
    )
    if not windows:
        raise ValueError(
            f"Not enough history ({data_start} to {data_end}) to form even one walk-forward "
            f"window with train={cfg.walk_forward.train_days}d validation={cfg.walk_forward.validation_days}d "
            f"test={cfg.walk_forward.test_days}d. Download more bars or shrink the window sizes."
        )

    higher_prefix = cfg.higher_timeframe.lower() if cfg.higher_timeframe else None
    tp_distance = _take_profit_distance(cfg, spec)
    sl_distance = _stop_loss_distance(cfg, spec)
    feature_columns = feature_columns_for(higher_prefix)

    account = Account(cfg.initial_balance, cfg.currency)
    window_results: list[WalkForwardWindowResult] = []
    all_test_rows: list[pd.DataFrame] = []
    all_trade_frames: list[pd.DataFrame] = []

    for window in windows:
        warmup_start = window.train_start - pd.Timedelta(minutes=WARMUP_BARS * base_minutes)
        base_slice = base_raw[(base_raw["time"] >= warmup_start) & (base_raw["time"] < window.test_end)]
        base_slice = base_slice.reset_index(drop=True)

        higher_slice = None
        if higher_raw is not None:
            htf_minutes = TIMEFRAME_MINUTES.get(cfg.higher_timeframe.upper())
            htf_warmup_start = window.train_start - pd.Timedelta(minutes=WARMUP_BARS * htf_minutes)
            higher_slice = higher_raw[
                (higher_raw["time"] >= htf_warmup_start) & (higher_raw["time"] < window.test_end)
            ].reset_index(drop=True)
            if len(higher_slice) >= 2:
                base_feats = compute_features(base_slice)
                higher_feats = compute_features(higher_slice)
                merged_for_audit = audit_merge(base_feats, higher_feats, higher_prefix)
                verify_higher_timeframe_alignment(merged_for_audit, higher_slice, higher_prefix)

        try:
            labeled = prepare_dataset(
                base_slice, cfg.side, tp_distance, sl_distance,
                max_bars_forward=cfg.execution.max_holding_bars,
                higher_raw=higher_slice, higher_prefix=higher_prefix or "htf",
            )
        except (ValueError, LookaheadError) as exc:
            window_results.append(
                WalkForwardWindowResult(window, 0, 0, 0, {}, {}, skipped_reason=str(exc))
            )
            continue

        train_split = labeled[(labeled["time"] >= window.train_start) & (labeled["time"] < window.train_end)]
        val_split = labeled[(labeled["time"] >= window.val_start) & (labeled["time"] < window.val_end)]
        test_split = labeled[(labeled["time"] >= window.test_start) & (labeled["time"] < window.test_end)]

        if len(train_split) < 50 or len(val_split) < 10 or len(test_split) < 5:
            window_results.append(
                WalkForwardWindowResult(
                    window, len(train_split), len(val_split), len(test_split), {}, {},
                    skipped_reason=(
                        f"Too few rows after feature/label warmup to train+evaluate "
                        f"(train={len(train_split)}, val={len(val_split)}, test={len(test_split)})."
                    ),
                )
            )
            continue

        model, _ = train_model(
            feature_columns=feature_columns, params=lgb_params,
            train_df=train_split, val_df=val_split, test_df=test_split,
        )
        test_split = test_split.copy()
        test_split["predicted_probability"] = model.predict(
            test_split[feature_columns], num_iteration=model.best_iteration
        )

        m_metrics = model_metrics(test_split["label"], test_split["predicted_probability"])
        trades = run_simulation(test_split, cfg, spec, account, window.index)
        window_trades_df = trades_to_frame(trades)
        window_equity = account.to_frame()
        window_equity = window_equity[
            (window_equity["time"] >= window.test_start) & (window_equity["time"] < window.test_end)
        ]
        t_metrics = trading_metrics(
            window_trades_df, window_equity, cfg.initial_balance, bars_per_year(cfg.timeframe)
        )

        window_results.append(
            WalkForwardWindowResult(
                window, len(train_split), len(val_split), len(test_split), m_metrics, t_metrics
            )
        )
        all_test_rows.append(test_split[["time", "label", "predicted_probability"]])
        if not window_trades_df.empty:
            all_trade_frames.append(window_trades_df)

    all_trades = pd.concat(all_trade_frames, ignore_index=True) if all_trade_frames else pd.DataFrame()
    equity_curve = account.to_frame()

    predictions = pd.concat(all_test_rows, ignore_index=True) if all_test_rows else pd.DataFrame()
    overall_model = {}
    if not predictions.empty:
        overall_model = model_metrics(predictions["label"], predictions["predicted_probability"])
    overall_trading = trading_metrics(all_trades, equity_curve, cfg.initial_balance, bars_per_year(cfg.timeframe))

    return WalkForwardResult(window_results, all_trades, equity_curve, predictions, overall_model, overall_trading)
