"""infer.latest_signal() end-to-end with a monkeypatched download_history —
ported from the earlier ad-hoc scratch test, never previously committed."""
from pathlib import Path

import lightgbm as lgb

from conftest import make_synthetic_ohlc
from train import feature_columns_for, prepare_dataset, train_model

import infer


def test_latest_signal_with_higher_timeframe_end_to_end(tmp_path: Path):
    base_raw = make_synthetic_ohlc(6000, freq="5min", seed=23)
    higher_raw = make_synthetic_ohlc(4593, freq="1h", start_time="2023-01-01", seed=24)

    dataset = prepare_dataset(
        base_raw, side="BUY", tp_distance=3.0, sl_distance=2.0, max_bars_forward=30,
        higher_raw=higher_raw, higher_prefix="h1",
    )
    model, _ = train_model(dataset, feature_columns=feature_columns_for("h1"))
    model_path = tmp_path / "test_mtf_model.txt"
    model.save_model(str(model_path))

    call_log = []

    def fake_download_history(symbol, timeframe, bars):
        call_log.append((symbol, timeframe, bars))
        if timeframe.upper() == "H1":
            return make_synthetic_ohlc(max(bars, 300), freq="1h", start_time="2023-06-01", seed=24)
        return make_synthetic_ohlc(max(bars, 300), freq="5min", start_time="2024-06-01", seed=23)

    original = infer.download_history
    infer.download_history = fake_download_history
    try:
        reloaded_model = lgb.Booster(model_file=str(model_path))
        signal = infer.latest_signal(
            reloaded_model, "XAUUSDm", "M5", lookback_bars=300,
            higher_timeframe="H1", higher_lookback_bars=300,
        )
    finally:
        infer.download_history = original

    assert signal["symbol"] == "XAUUSDm"
    assert signal["side"] in ("BUY", "SELL", "NO_TRADE")
    assert 0 <= signal["confidence"] <= 100
    assert len(call_log) == 2, f"expected two download_history calls (base + higher), got {call_log}"
    assert any(tf == "H1" for _, tf, _ in call_log)
