"""Multi-timeframe training pipeline checks (train.py + features.py
together) — ported from the earlier ad-hoc scratch test, never previously
committed."""
import numpy as np

from conftest import make_synthetic_ohlc
from features import FEATURE_COLUMNS
from mt5_data import bars_to_cover_same_span
from train import feature_columns_for, prepare_dataset, train_model


def test_bars_to_cover_same_span_arithmetic():
    expected = int(250000 / 60 * 1.1) + 10
    got = bars_to_cover_same_span("M5", 50000, "H1")
    assert got == expected
    assert bars_to_cover_same_span("M5", 50000, "H1") < bars_to_cover_same_span("M5", 50000, "M15")


def test_feature_columns_for():
    assert feature_columns_for(None) == FEATURE_COLUMNS
    with_htf = feature_columns_for("h1")
    assert len(with_htf) == 2 * len(FEATURE_COLUMNS)
    assert all(c.startswith("h1_") for c in with_htf[len(FEATURE_COLUMNS):])


def test_prepare_dataset_with_higher_timeframe_produces_clean_columns():
    base_raw = make_synthetic_ohlc(6000, freq="5min", seed=23)
    higher_bars = bars_to_cover_same_span("M5", 6000, "H1")
    higher_raw = make_synthetic_ohlc(higher_bars, freq="1h", start_time="2023-01-01", seed=24)

    dataset = prepare_dataset(
        base_raw, side="BUY", tp_distance=3.0, sl_distance=2.0, max_bars_forward=30,
        higher_raw=higher_raw, higher_prefix="h1",
    )
    expected_cols = feature_columns_for("h1")
    for c in expected_cols:
        assert c in dataset.columns
        assert not dataset[c].isna().any()
    assert len(dataset) > 500


def test_no_lookahead_through_full_prepare_dataset_pipeline():
    base_raw = make_synthetic_ohlc(6000, freq="5min", seed=23)
    higher_bars = bars_to_cover_same_span("M5", 6000, "H1")
    higher_raw = make_synthetic_ohlc(higher_bars, freq="1h", start_time="2023-01-01", seed=24)
    expected_cols = feature_columns_for("h1")

    full = prepare_dataset(
        base_raw, side="BUY", tp_distance=3.0, sl_distance=2.0, max_bars_forward=30,
        higher_raw=higher_raw, higher_prefix="h1",
    )
    truncated = prepare_dataset(
        base_raw.iloc[:3000].copy(), side="BUY", tp_distance=3.0, sl_distance=2.0, max_bars_forward=30,
        higher_raw=higher_raw, higher_prefix="h1",
    )
    common_time = truncated["time"].iloc[500]
    full_row = full[full["time"] == common_time]
    trunc_row = truncated[truncated["time"] == common_time]
    assert len(full_row) == 1 and len(trunc_row) == 1
    for c in expected_cols:
        a, b = full_row.iloc[0][c], trunc_row.iloc[0][c]
        assert np.isclose(a, b, rtol=1e-9, atol=1e-9), f"LOOKAHEAD in {c} at {common_time}"


def test_train_model_with_multitimeframe_features():
    base_raw = make_synthetic_ohlc(6000, freq="5min", seed=23)
    higher_bars = bars_to_cover_same_span("M5", 6000, "H1")
    higher_raw = make_synthetic_ohlc(higher_bars, freq="1h", start_time="2023-01-01", seed=24)
    expected_cols = feature_columns_for("h1")
    dataset = prepare_dataset(
        base_raw, side="BUY", tp_distance=3.0, sl_distance=2.0, max_bars_forward=30,
        higher_raw=higher_raw, higher_prefix="h1",
    )
    model, metrics = train_model(dataset, feature_columns=expected_cols)
    assert model.feature_name() == expected_cols
    preds = model.predict(dataset[expected_cols])
    assert np.isfinite(preds).all() and (preds >= 0).all() and (preds <= 1).all()


def test_train_model_accepts_explicit_train_val_test_splits():
    """The walk-forward backtester needs exact calendar-boundary control
    over each split, not train_model's default internal 70/15/15 fraction
    split — this is the backward-compatible extension backtest/walk_forward.py
    relies on."""
    base_raw = make_synthetic_ohlc(3000, freq="5min", seed=5)
    dataset = prepare_dataset(base_raw, side="BUY", tp_distance=3.0, sl_distance=2.0, max_bars_forward=20)
    n = len(dataset)
    train_df, val_df, test_df = dataset.iloc[: n // 2], dataset.iloc[n // 2 : n * 3 // 4], dataset.iloc[n * 3 // 4 :]
    model, metrics = train_model(
        feature_columns=FEATURE_COLUMNS, train_df=train_df, val_df=val_df, test_df=test_df
    )
    assert metrics["train_rows"] == len(train_df)
    assert metrics["test_rows"] == len(test_df)

    try:
        train_model(dataset=dataset, train_df=train_df, val_df=val_df, test_df=test_df)
        assert False, "passing both dataset and explicit splits should be rejected as ambiguous"
    except ValueError:
        pass
