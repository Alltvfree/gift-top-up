"""Kronos live inference loop.

Loads a model trained by train.py, and every `poll_seconds` pulls the most
recent bars, computes the same features used in training, predicts
P(TP-before-SL), and publishes a BUY/SELL/NO_TRADE signal to Supabase.

Run this continuously — same always-on pattern as
tilly-trading/mt5-bridge/bridge.py (a Scheduled Task on Windows, tied to an
interactive logon session for the same MT5-IPC reason bridge.py documents).
It can run on the same machine as bridge.py or a separate one, as long as
that machine also has a logged-in MT5 terminal for mt5_data.py to attach to.
"""
from __future__ import annotations

import time

import lightgbm as lgb

from features import FEATURE_COLUMNS, compute_features
from mt5_data import connect, disconnect, download_history
from publish_signal import publish_signal

# From the project notes' example decision rule: BUY only when
# P(TP-before-SL) > 0.60. Symmetric on the sell side. Between the two
# thresholds the model isn't confident enough in either direction, which is
# NO_TRADE — an intentional output, not a fallback for missing data.
BUY_THRESHOLD = 0.60
SELL_THRESHOLD = 1 - BUY_THRESHOLD


def latest_signal(model: lgb.Booster, symbol: str, timeframe: str, lookback_bars: int) -> dict:
    raw = download_history(symbol, timeframe, lookback_bars)
    feats = compute_features(raw).dropna(subset=FEATURE_COLUMNS)
    if feats.empty:
        raise RuntimeError(
            f"Not enough history to compute features yet ({lookback_bars} bars requested)."
        )

    latest = feats.iloc[[-1]]
    p_tp = float(model.predict(latest[FEATURE_COLUMNS])[0])

    if p_tp >= BUY_THRESHOLD:
        side, confidence = "BUY", p_tp * 100
    elif p_tp <= SELL_THRESHOLD:
        side, confidence = "SELL", (1 - p_tp) * 100
    else:
        side, confidence = "NO_TRADE", 50.0

    return {
        "symbol": symbol,
        "side": side,
        "confidence": round(confidence, 1),
        "timeframe": timeframe,
        "note": f"P(TP-before-SL)={p_tp:.3f}",
    }


def run_loop(
    model_path: str, symbol: str, timeframe: str, lookback_bars: int, poll_seconds: int
) -> None:
    model = lgb.Booster(model_file=model_path)
    connect()
    try:
        while True:
            try:
                signal = latest_signal(model, symbol, timeframe, lookback_bars)
                publish_signal(**signal)
                print(f"Published: {signal}")
            except Exception as exc:  # noqa: BLE001 - one bad cycle shouldn't kill the loop
                print(f"Inference cycle failed: {exc}")
            time.sleep(poll_seconds)
    finally:
        disconnect()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="kronos_model.txt")
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument(
        "--lookback-bars",
        type=int,
        default=300,
        help="Recent bars to fetch each cycle — only needs enough for the slowest indicator (EMA 200) to warm up, not the full training history.",
    )
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()
    run_loop(args.model, args.symbol, args.timeframe, args.lookback_bars, args.poll_seconds)


if __name__ == "__main__":
    main()
