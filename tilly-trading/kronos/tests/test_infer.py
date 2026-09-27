"""infer.latest_signal() end-to-end with a monkeypatched download_history —
ported from the earlier ad-hoc scratch test, never previously committed.
Exercises TWO models (BUY-trained and SELL-trained), matching infer.py's
current dual-model design — see infer.py's module docstring for why a
single model's complement is no longer used for the other side.
"""
from pathlib import Path

import lightgbm as lgb

from conftest import make_synthetic_ohlc
from train import feature_columns_for, prepare_dataset, train_model

import infer


def _train_side(base_raw, higher_raw, side: str, tmp_path: Path, name: str):
    dataset = prepare_dataset(
        base_raw, side=side, tp_distance=3.0, sl_distance=2.0, max_bars_forward=30,
        higher_raw=higher_raw, higher_prefix="h1",
    )
    model, _ = train_model(dataset, feature_columns=feature_columns_for("h1"))
    model_path = tmp_path / name
    model.save_model(str(model_path))
    return model_path


def test_latest_signal_with_higher_timeframe_end_to_end(tmp_path: Path):
    base_raw = make_synthetic_ohlc(6000, freq="5min", seed=23)
    higher_raw = make_synthetic_ohlc(4593, freq="1h", start_time="2023-01-01", seed=24)

    buy_model_path = _train_side(base_raw, higher_raw, "BUY", tmp_path, "buy_model.txt")
    sell_model_path = _train_side(base_raw, higher_raw, "SELL", tmp_path, "sell_model.txt")

    call_log = []

    def fake_download_history(symbol, timeframe, bars):
        call_log.append((symbol, timeframe, bars))
        if timeframe.upper() == "H1":
            return make_synthetic_ohlc(max(bars, 300), freq="1h", start_time="2023-06-01", seed=24)
        return make_synthetic_ohlc(max(bars, 300), freq="5min", start_time="2024-06-01", seed=23)

    original = infer.download_history
    infer.download_history = fake_download_history
    try:
        model_buy = lgb.Booster(model_file=str(buy_model_path))
        model_sell = lgb.Booster(model_file=str(sell_model_path))
        signal = infer.latest_signal(
            model_buy, model_sell, "XAUUSDm", "M5", lookback_bars=300,
            higher_timeframe="H1", higher_lookback_bars=300,
        )
    finally:
        infer.download_history = original

    assert signal["symbol"] == "XAUUSDm"
    assert signal["side"] in ("BUY", "SELL", "NO_TRADE")
    assert 0 <= signal["confidence"] <= 100
    assert "P(BUY TP-before-SL)=" in signal["note"] and "P(SELL TP-before-SL)=" in signal["note"]
    # One shared feature computation (base+higher) feeds BOTH models — features
    # are side-independent, so there's no need to download or compute twice.
    assert len(call_log) == 2, f"expected two download_history calls (base + higher), got {call_log}"
    assert sum(1 for _, tf, _ in call_log if tf == "H1") == 1


def test_conflicting_signals_yield_no_trade(monkeypatch):
    """Both models independently confident in opposite directions is a
    conflict, not a tiebreak — mirrors backtest/signal_engine.py."""

    class _StubModel:
        def __init__(self, p):
            self.p = p

        def predict(self, x):
            return [self.p]

    def fake_download_history(symbol, timeframe, bars):
        return make_synthetic_ohlc(max(bars, 300), freq="5min", seed=1)

    monkeypatch.setattr(infer, "download_history", fake_download_history)
    signal = infer.latest_signal(
        _StubModel(0.99), _StubModel(0.99), "XAUUSDm", "M5", lookback_bars=300,
        buy_threshold=0.60, sell_threshold=0.60,
    )
    assert signal["side"] == "NO_TRADE"
