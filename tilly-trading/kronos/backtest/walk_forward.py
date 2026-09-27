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

Trains TWO models per window — one on side="BUY" labels, one on
side="SELL" — not one model whose complement stands in for the other
direction. A real BTCUSDm run with the single-model version produced 641
SELL trades out of 643, all of them driven by "P(BUY) is low", never by an
actual trained SELL-side model; see signal_engine.py's module docstring.
Both sides share one feature computation per window (features are
direction-independent — only the label differs), so this costs one extra
LightGBM training pass per window, not a second full pipeline.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # to import train/features/labels as flat modules

from features import compute_features, merge_higher_timeframe  # noqa: E402
from labels import label_tp_before_sl  # noqa: E402
from train import feature_columns_for, train_model  # noqa: E402

from .account import Account  # noqa: E402
from .config import BacktestConfig  # noqa: E402
from .leakage_audit import audit_merge, verify_higher_timeframe_alignment  # noqa: E402
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

MIN_TRAIN_ROWS, MIN_VAL_ROWS, MIN_TEST_ROWS = 50, 10, 5


@dataclass
class WalkForwardWindowResult:
    window: Window
    train_rows_buy: int
    val_rows_buy: int
    train_rows_sell: int
    val_rows_sell: int
    test_rows: int
    model_metrics_buy: dict
    model_metrics_sell: dict
    trading_metrics: dict
    skipped_reason: str | None = None


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindowResult] = field(default_factory=list)
    all_trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    predictions: pd.DataFrame = field(default_factory=pd.DataFrame)
    overall_model_metrics_buy: dict = field(default_factory=dict)
    overall_model_metrics_sell: dict = field(default_factory=dict)
    overall_trading_metrics: dict = field(default_factory=dict)


def _stop_loss_distance(cfg: BacktestConfig, spec: SymbolSpec) -> float:
    return cfg.stop_loss.value * spec.point if cfg.stop_loss.type == "points" else cfg.stop_loss.value


def _take_profit_distance(cfg: BacktestConfig, spec: SymbolSpec) -> float:
    return cfg.take_profit.value * spec.point if cfg.take_profit.type == "points" else cfg.take_profit.value


def _calendar_split(dataset: pd.DataFrame, window: Window) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train = dataset[(dataset["time"] >= window.train_start) & (dataset["time"] < window.train_end)]
    val = dataset[(dataset["time"] >= window.val_start) & (dataset["time"] < window.val_end)]
    test = dataset[(dataset["time"] >= window.test_start) & (dataset["time"] < window.test_end)]
    return train, val, test


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

        # No try/except here: a LookaheadError below means the higher-
        # timeframe merge is corrupted (the exact bug this project already
        # found and fixed once — see README) and must halt the whole run
        # loudly, never be swallowed into a per-window skip. Per-window
        # data-availability issues (too little history for this window) are
        # handled separately below, after dropna, as an explicit row-count
        # check — not as an exception.
        higher_slice = None
        if higher_raw is not None:
            htf_minutes = TIMEFRAME_MINUTES.get(cfg.higher_timeframe.upper())
            htf_warmup_start = window.train_start - pd.Timedelta(minutes=WARMUP_BARS * htf_minutes)
            higher_slice = higher_raw[
                (higher_raw["time"] >= htf_warmup_start) & (higher_raw["time"] < window.test_end)
            ].reset_index(drop=True)

        base_feats = compute_features(base_slice)
        if higher_slice is not None and len(higher_slice) >= 2:
            higher_feats = compute_features(higher_slice)
            merged_for_audit = audit_merge(base_feats, higher_feats, higher_prefix)
            verify_higher_timeframe_alignment(merged_for_audit, higher_slice, higher_prefix)
            base_feats = merge_higher_timeframe(base_feats, higher_feats, prefix=higher_prefix)

        base_feats = base_feats.reset_index(drop=True)
        base_slice_reset = base_slice.reset_index(drop=True)
        base_feats["label_buy"] = label_tp_before_sl(
            base_slice_reset, tp_distance, sl_distance, "BUY", cfg.execution.max_holding_bars
        ).values
        base_feats["label_sell"] = label_tp_before_sl(
            base_slice_reset, tp_distance, sl_distance, "SELL", cfg.execution.max_holding_bars
        ).values

        buy_rows = base_feats.dropna(subset=[*feature_columns, "label_buy"]).reset_index(drop=True)
        sell_rows = base_feats.dropna(subset=[*feature_columns, "label_sell"]).reset_index(drop=True)
        # The simulator needs ONE shared bar sequence with both probabilities
        # attached, so the test split requires both sides' labels resolved —
        # a bar where (say) only the BUY outcome resolved within the horizon
        # would otherwise let one side "see" a bar the other can't be scored
        # on, which would make the two sides silently incomparable.
        test_rows_both = base_feats.dropna(subset=[*feature_columns, "label_buy", "label_sell"]).reset_index(drop=True)

        buy_train, buy_val, _ = _calendar_split(buy_rows, window)
        sell_train, sell_val, _ = _calendar_split(sell_rows, window)
        _, _, test_split = _calendar_split(test_rows_both, window)

        counts = (len(buy_train), len(buy_val), len(sell_train), len(sell_val), len(test_split))
        if (
            len(buy_train) < MIN_TRAIN_ROWS or len(buy_val) < MIN_VAL_ROWS
            or len(sell_train) < MIN_TRAIN_ROWS or len(sell_val) < MIN_VAL_ROWS
            or len(test_split) < MIN_TEST_ROWS
        ):
            window_results.append(
                WalkForwardWindowResult(
                    window, *counts, {}, {}, {},
                    skipped_reason=(
                        f"Too few rows after feature/label warmup to train+evaluate both sides "
                        f"(buy_train={counts[0]}, buy_val={counts[1]}, sell_train={counts[2]}, "
                        f"sell_val={counts[3]}, test={counts[4]})."
                    ),
                )
            )
            continue

        buy_test_for_training = test_split.rename(columns={"label_buy": "label"})
        sell_test_for_training = test_split.rename(columns={"label_sell": "label"})
        model_buy, _ = train_model(
            feature_columns=feature_columns, params=lgb_params,
            train_df=buy_train.rename(columns={"label_buy": "label"}),
            val_df=buy_val.rename(columns={"label_buy": "label"}),
            test_df=buy_test_for_training,
        )
        model_sell, _ = train_model(
            feature_columns=feature_columns, params=lgb_params,
            train_df=sell_train.rename(columns={"label_sell": "label"}),
            val_df=sell_val.rename(columns={"label_sell": "label"}),
            test_df=sell_test_for_training,
        )

        test_split = test_split.copy()
        test_split["predicted_probability_buy"] = model_buy.predict(
            test_split[feature_columns], num_iteration=model_buy.best_iteration
        )
        test_split["predicted_probability_sell"] = model_sell.predict(
            test_split[feature_columns], num_iteration=model_sell.best_iteration
        )

        m_metrics_buy = model_metrics(test_split["label_buy"], test_split["predicted_probability_buy"])
        m_metrics_sell = model_metrics(test_split["label_sell"], test_split["predicted_probability_sell"])
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
                window, *counts, m_metrics_buy, m_metrics_sell, t_metrics
            )
        )
        all_test_rows.append(
            test_split[[
                "time", "label_buy", "label_sell",
                "predicted_probability_buy", "predicted_probability_sell",
            ]]
        )
        if not window_trades_df.empty:
            all_trade_frames.append(window_trades_df)

    all_trades = pd.concat(all_trade_frames, ignore_index=True) if all_trade_frames else pd.DataFrame()
    equity_curve = account.to_frame()

    predictions = pd.concat(all_test_rows, ignore_index=True) if all_test_rows else pd.DataFrame()
    overall_model_buy, overall_model_sell = {}, {}
    if not predictions.empty:
        overall_model_buy = model_metrics(predictions["label_buy"], predictions["predicted_probability_buy"])
        overall_model_sell = model_metrics(predictions["label_sell"], predictions["predicted_probability_sell"])
    overall_trading = trading_metrics(all_trades, equity_curve, cfg.initial_balance, bars_per_year(cfg.timeframe))

    return WalkForwardResult(
        window_results, all_trades, equity_curve, predictions,
        overall_model_buy, overall_model_sell, overall_trading,
    )
