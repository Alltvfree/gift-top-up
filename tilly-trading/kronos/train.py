"""Kronos training: a LightGBM binary classifier predicting P(TP-before-SL).

Chronological split only — train/validation/test are contiguous, ordered
time windows (never a random shuffle), so the model is never evaluated on
data that occurred before data it trained on. Full walk-forward validation
(retraining across multiple rolling windows, per the project notes' Phase 5)
is a documented follow-up, not implemented here — this is Phase 1/2: a
single chronological split, enough to tell whether the approach has any
signal before investing in the rest of the roadmap.

Everything in this file operates on plain pandas DataFrames and has been
tested against synthetic data (see the project's test suite) — it has no
MT5 dependency itself. Only main()'s download step (mt5_data.py) does.
"""
from __future__ import annotations

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score

from features import FEATURE_COLUMNS, compute_features
from labels import label_tp_before_sl


def chronological_split(
    df: pd.DataFrame, train_frac: float = 0.7, val_frac: float = 0.15
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not 0 < train_frac < 1 or not 0 < val_frac < 1 or train_frac + val_frac >= 1:
        raise ValueError("train_frac and val_frac must be positive and sum to less than 1.")
    n = len(df)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))
    return df.iloc[:train_end], df.iloc[train_end:val_end], df.iloc[val_end:]


def prepare_dataset(
    raw: pd.DataFrame,
    side: str,
    tp_distance: float,
    sl_distance: float,
    max_bars_forward: int = 50,
) -> pd.DataFrame:
    """raw: OHLC bars (see mt5_data.download_history's output shape).
    Returns feature columns + a `label` column, with rows dropped wherever
    either isn't available (early rows before indicators have enough
    history; trailing rows whose trade outcome isn't resolved yet)."""
    feats = compute_features(raw)
    feats["label"] = label_tp_before_sl(raw, tp_distance, sl_distance, side, max_bars_forward)
    return feats.dropna(subset=[*FEATURE_COLUMNS, "label"]).reset_index(drop=True)


def train_model(
    dataset: pd.DataFrame, params: dict | None = None
) -> tuple[lgb.Booster, dict]:
    train_df, val_df, test_df = chronological_split(dataset)
    if len(train_df) == 0 or len(val_df) == 0 or len(test_df) == 0:
        raise ValueError("Not enough rows to split into train/val/test — need more history.")

    x_train, y_train = train_df[FEATURE_COLUMNS], train_df["label"]
    x_val, y_val = val_df[FEATURE_COLUMNS], val_df["label"]
    x_test, y_test = test_df[FEATURE_COLUMNS], test_df["label"]

    lgb_params = {
        "objective": "binary",
        "metric": "auc",
        "verbosity": -1,
        "num_leaves": 31,
        "learning_rate": 0.05,
        **(params or {}),
    }
    train_set = lgb.Dataset(x_train, label=y_train)
    val_set = lgb.Dataset(x_val, label=y_val, reference=train_set)

    model = lgb.train(
        lgb_params,
        train_set,
        num_boost_round=500,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(30, verbose=False), lgb.log_evaluation(0)],
    )

    test_pred = model.predict(x_test, num_iteration=model.best_iteration)
    metrics = {
        "train_rows": len(train_df),
        "val_rows": len(val_df),
        "test_rows": len(test_df),
        "test_auc": roc_auc_score(y_test, test_pred) if y_test.nunique() > 1 else float("nan"),
        "test_accuracy": accuracy_score(y_test, test_pred >= 0.5),
        "positive_rate_train": float(y_train.mean()),
        "positive_rate_test": float(y_test.mean()),
        "best_iteration": model.best_iteration,
    }
    return model, metrics


def main() -> None:
    import argparse

    from mt5_data import connect, disconnect, download_history

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--bars", type=int, default=50000)
    parser.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    parser.add_argument("--tp", type=float, default=3.0, help="Take-profit distance in price units.")
    parser.add_argument("--sl", type=float, default=2.0, help="Stop-loss distance in price units.")
    parser.add_argument("--max-bars-forward", type=int, default=50)
    parser.add_argument("--out", default="kronos_model.txt")
    args = parser.parse_args()

    connect()
    try:
        raw = download_history(args.symbol, args.timeframe, args.bars)
    finally:
        disconnect()

    dataset = prepare_dataset(raw, args.side, args.tp, args.sl, args.max_bars_forward)
    model, metrics = train_model(dataset)
    model.save_model(args.out)

    print(f"Saved model to {args.out}")
    for key, value in metrics.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
