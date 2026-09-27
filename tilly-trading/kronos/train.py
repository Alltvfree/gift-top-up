"""Kronos training: a LightGBM binary classifier predicting P(TP-before-SL).

Chronological split only — train/validation/test are contiguous, ordered
time windows (never a random shuffle), so the model is never evaluated on
data that occurred before data it trained on. This file itself still does
just one single chronological split (Phase 1/2 — enough to tell whether the
approach has any signal at all); full walk-forward validation (retraining
across multiple rolling windows) is `backtest/walk_forward.py`, which calls
back into this file's own `prepare_dataset`/`train_model` per window rather
than duplicating them — see kronos/README.md's "Phase 3" section.

Optionally adds a higher timeframe's own features as context (--higher-
timeframe), via features.merge_higher_timeframe — e.g. training on M5 with
H1 features attached, so the model has some sense of the larger trend it's
sitting inside, not just the base timeframe in isolation.

Everything in this file operates on plain pandas DataFrames and has been
tested against synthetic data (see the project's test suite) — it has no
MT5 dependency itself. Only main()'s download step (mt5_data.py) does.
"""
from __future__ import annotations

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score

from features import FEATURE_COLUMNS, compute_features, merge_higher_timeframe
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


def feature_columns_for(higher_prefix: str | None, news_windows: tuple[int, ...] | None = None) -> list[str]:
    """The full feature-column list a dataset/model uses — base columns,
    the higher-timeframe columns (same names, prefixed) if a higher
    timeframe was merged in, and the news feature columns (news/features.py)
    if news_windows is given. Centralized here so prepare_dataset,
    train_model, and infer.py's latest_signal all derive it the same way
    instead of three copies of this string-building drifting apart.

    news_windows is NOT threaded through backtest/walk_forward.py — see
    prepare_dataset's own docstring for why wiring news features into the
    walk-forward backtester specifically would be actively misleading
    right now, not just premature.
    """
    cols = list(FEATURE_COLUMNS)
    if higher_prefix:
        cols += [f"{higher_prefix}_{c}" for c in FEATURE_COLUMNS]
    if news_windows:
        from news.features import news_feature_columns  # noqa: PLC0415 - optional, avoid a hard import-time dependency

        cols += news_feature_columns(news_windows)
    return cols


def prepare_dataset(
    raw: pd.DataFrame,
    side: str,
    tp_distance: float,
    sl_distance: float,
    max_bars_forward: int = 50,
    higher_raw: pd.DataFrame | None = None,
    higher_prefix: str = "htf",
    news_articles: pd.DataFrame | None = None,
    news_windows: tuple[int, ...] | None = None,
) -> pd.DataFrame:
    """raw: OHLC bars (see mt5_data.download_history's output shape).
    higher_raw: optionally, a second, higher timeframe's own OHLC bars
    covering the same (or a wider) span — its features get merged in via
    merge_higher_timeframe, prefixed with `higher_prefix`.
    news_articles: optionally, a news/store.load_articles()-shaped
    DataFrame — its features get merged in via news.features.attach_news_
    features (timestamp-safe; see that module's own docstring). Meant for
    infer.py's LIVE predictions and for retraining once you've collected
    real news history over time (news/README.md) — deliberately NOT
    threaded into backtest/walk_forward.py: a walk-forward test window
    from before you started collecting has ZERO real news coverage, so
    every news feature would silently read as 0 for most of history and
    only become real in the most recent slice — not a fair test of
    whether the feature helps, just a feature that's usually absent
    dressed up as one that's usually neutral. Train/test on it live,
    honestly, once real coverage actually exists, rather than backtest
    against a history the news pipeline was never actually watching.

    Returns feature columns + a `label` column, with rows dropped wherever
    either isn't available (early rows before indicators have enough
    history; trailing rows whose trade outcome isn't resolved yet; and —
    with a higher timeframe — the leading rows before it has any confirmed
    bar to attach yet either).
    """
    raw = raw.reset_index(drop=True)
    labels = label_tp_before_sl(raw, tp_distance, sl_distance, side, max_bars_forward).reset_index(
        drop=True
    )

    feats = compute_features(raw)
    if higher_raw is not None:
        higher_feats = compute_features(higher_raw.reset_index(drop=True))
        feats = merge_higher_timeframe(feats, higher_feats, prefix=higher_prefix)
    if news_articles is not None:
        from news.features import attach_news_features  # noqa: PLC0415 - optional, avoid a hard import-time dependency
        from news.features import DEFAULT_WINDOWS_MINUTES as NEWS_DEFAULT_WINDOWS_MINUTES  # noqa: PLC0415,N812

        news_windows = news_windows or NEWS_DEFAULT_WINDOWS_MINUTES
        feats = attach_news_features(feats, news_articles, news_windows)

    # merge_asof (inside merge_higher_timeframe) re-sorts by time and can
    # hand back a fresh index — reset explicitly and assign the label by
    # position (.values), not by index-label alignment, so there's no
    # chance of a silent misalignment between labels and their rows.
    feats = feats.reset_index(drop=True)
    feats["label"] = labels.values

    cols = feature_columns_for(
        higher_prefix if higher_raw is not None else None,
        news_windows if news_articles is not None else None,
    )
    return feats.dropna(subset=[*cols, "label"]).reset_index(drop=True)


def train_model(
    dataset: pd.DataFrame | None = None,
    feature_columns: list[str] | None = None,
    params: dict | None = None,
    train_df: pd.DataFrame | None = None,
    val_df: pd.DataFrame | None = None,
    test_df: pd.DataFrame | None = None,
) -> tuple[lgb.Booster, dict]:
    """Either pass `dataset` alone (the original single-chronological-split
    behavior: internally split 70/15/15 via chronological_split), or pass
    `train_df`/`val_df`/`test_df` explicitly (used by backtest/walk_forward.py,
    which needs exact calendar-boundary control over each split that a
    fixed 70/15/15 fraction can't give it). Passing both is an error — it's
    ambiguous which one should win."""
    feature_columns = feature_columns or FEATURE_COLUMNS
    explicit_splits = train_df is not None or val_df is not None or test_df is not None
    if explicit_splits and dataset is not None:
        raise ValueError("Pass either `dataset` or train_df/val_df/test_df, not both.")
    if explicit_splits:
        if train_df is None or val_df is None or test_df is None:
            raise ValueError("train_df, val_df, and test_df must all be given together.")
    elif dataset is not None:
        train_df, val_df, test_df = chronological_split(dataset)
    else:
        raise ValueError("Must pass either `dataset` or train_df/val_df/test_df.")

    if len(train_df) == 0 or len(val_df) == 0 or len(test_df) == 0:
        raise ValueError("Not enough rows to split into train/val/test — need more history.")

    x_train, y_train = train_df[feature_columns], train_df["label"]
    x_val, y_val = val_df[feature_columns], val_df["label"]
    x_test, y_test = test_df[feature_columns], test_df["label"]

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

    from mt5_data import bars_to_cover_same_span, connect, disconnect, download_history

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument("--bars", type=int, default=50000)
    parser.add_argument(
        "--higher-timeframe",
        default=None,
        help="e.g. H1 - adds that timeframe's own features as context (see "
        "features.merge_higher_timeframe). Omit to train on --timeframe alone.",
    )
    parser.add_argument("--side", choices=["BUY", "SELL"], default="BUY")
    parser.add_argument("--tp", type=float, default=3.0, help="Take-profit distance in price units.")
    parser.add_argument("--sl", type=float, default=2.0, help="Stop-loss distance in price units.")
    parser.add_argument("--max-bars-forward", type=int, default=50)
    parser.add_argument(
        "--news-store",
        default=None,
        help="Path to a news/store.py JSONL article file (see collect_news.py) - adds news/features.py's "
        "sentiment/count features. Only meaningful once you've collected real history over time; see "
        "prepare_dataset's own docstring for why this isn't available in backtest/walk_forward.py.",
    )
    parser.add_argument("--out", default="kronos_model.txt")
    args = parser.parse_args()

    higher_prefix = args.higher_timeframe.lower() if args.higher_timeframe else None
    news_articles = None
    if args.news_store:
        from news.store import load_articles

        news_articles = load_articles(args.news_store)
        print(f"Loaded {len(news_articles)} articles from {args.news_store}")

    connect()
    try:
        raw = download_history(args.symbol, args.timeframe, args.bars)
        higher_raw = None
        if args.higher_timeframe:
            higher_bars = bars_to_cover_same_span(args.timeframe, args.bars, args.higher_timeframe)
            higher_raw = download_history(args.symbol, args.higher_timeframe, higher_bars)
    finally:
        disconnect()

    dataset = prepare_dataset(
        raw,
        args.side,
        args.tp,
        args.sl,
        args.max_bars_forward,
        higher_raw=higher_raw,
        higher_prefix=higher_prefix or "htf",
        news_articles=news_articles,
    )
    news_windows = (15, 60, 240) if news_articles is not None else None
    model, metrics = train_model(dataset, feature_columns=feature_columns_for(higher_prefix, news_windows))
    model.save_model(args.out)

    print(f"Saved model to {args.out}")
    for key, value in metrics.items():
        print(f"  {key}: {value}")
    if args.higher_timeframe:
        print(f"  multi_timeframe: base={args.timeframe} higher={args.higher_timeframe}")
    if news_articles is not None:
        print(f"  news_features: {len(news_articles)} articles from {args.news_store}")


if __name__ == "__main__":
    main()
