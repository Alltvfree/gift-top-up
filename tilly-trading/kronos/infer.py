"""Kronos live inference loop.

Loads TWO models trained by train.py — one trained with --side BUY, one
with --side SELL — and every `poll_seconds` pulls the most recent bars,
computes the same features used in training, predicts each model's own
P(TP-before-SL) for its own direction, and publishes a BUY/SELL/NO_TRADE
signal to Supabase.

Two models, not one: an earlier version of this file used a single
BUY-trained model and treated "P(BUY) is low" as a SELL signal
(SELL_THRESHOLD = 1 - BUY_THRESHOLD). A real walk-forward backtest against
BTCUSDm caught why that's wrong — it produced 641 SELL trades out of 643,
none of them ever validated by an actual SELL-trained model, because "the
market probably won't let a BUY win" is not the same claim as "a SELL will
win." See backtest/signal_engine.py's module docstring for the full story.
Train both directions with train.py (--side BUY and --side SELL, same
symbol/timeframe/TP/SL, two separate --out files) before running this.

If the models were trained with --higher-timeframe, pass the matching
--higher-timeframe here too — the feature set has to line up exactly with
what they were trained on, or predict() will fail on a missing column
(a loud, immediate error, not a silent misprediction).

Run this continuously — same always-on pattern as
tilly-trading/mt5-bridge/bridge.py (a Scheduled Task on Windows, tied to an
interactive logon session for the same MT5-IPC reason bridge.py documents).
It can run on the same machine as bridge.py or a separate one, as long as
that machine also has a logged-in MT5 terminal for mt5_data.py to attach to.
"""
from __future__ import annotations

import time

import lightgbm as lgb

from features import compute_features, merge_higher_timeframe
from mt5_data import connect, disconnect, download_history
from publish_signal import publish_signal
from train import feature_columns_for

# Each threshold applies to its OWN model's own probability — not a
# complementary pair on one probability. See this file's module docstring.
BUY_THRESHOLD = 0.60
SELL_THRESHOLD = 0.60


def latest_signal(
    model_buy: lgb.Booster,
    model_sell: lgb.Booster,
    symbol: str,
    timeframe: str,
    lookback_bars: int,
    higher_timeframe: str | None = None,
    higher_lookback_bars: int = 300,
    buy_threshold: float = BUY_THRESHOLD,
    sell_threshold: float = SELL_THRESHOLD,
    news_store_path: str | None = None,
    news_windows: tuple[int, ...] | None = None,
) -> dict:
    """news_store_path: only pass this if BOTH models were trained with
    train.py --news-store (see that file's own docstring for why this
    can't come from backtest/walk_forward.py) — must match, or predict()
    fails loudly on a missing feature column rather than mispredicting
    silently, same as a --higher-timeframe mismatch."""
    raw = download_history(symbol, timeframe, lookback_bars)
    feats = compute_features(raw)

    higher_prefix = higher_timeframe.lower() if higher_timeframe else None
    if higher_timeframe:
        higher_raw = download_history(symbol, higher_timeframe, higher_lookback_bars)
        higher_feats = compute_features(higher_raw)
        feats = merge_higher_timeframe(feats, higher_feats, prefix=higher_prefix)

    if news_store_path:
        from news.features import DEFAULT_WINDOWS_MINUTES, attach_news_features
        from news.store import load_articles

        news_windows = news_windows or DEFAULT_WINDOWS_MINUTES
        articles = load_articles(news_store_path)  # reloaded fresh every cycle — the store keeps growing live
        feats = attach_news_features(feats, articles, news_windows)

    feature_columns = feature_columns_for(higher_prefix, news_windows if news_store_path else None)
    feats = feats.dropna(subset=feature_columns)
    if feats.empty:
        raise RuntimeError(
            f"Not enough history to compute features yet ({lookback_bars} bars requested)."
        )

    latest = feats.iloc[[-1]]
    p_buy = float(model_buy.predict(latest[feature_columns])[0])
    p_sell = float(model_sell.predict(latest[feature_columns])[0])

    buy_signal = p_buy >= buy_threshold
    sell_signal = p_sell >= sell_threshold
    if buy_signal and sell_signal:
        # Both models independently confident, in opposite directions — a
        # genuine conflict, not a tie to break. Sit out, same as
        # backtest/signal_engine.py's decide_side().
        side, confidence = "NO_TRADE", 50.0
    elif buy_signal:
        side, confidence = "BUY", p_buy * 100
    elif sell_signal:
        side, confidence = "SELL", p_sell * 100
    else:
        side, confidence = "NO_TRADE", 50.0

    return {
        "symbol": symbol,
        "side": side,
        "confidence": round(confidence, 1),
        "timeframe": timeframe,
        "note": f"P(BUY TP-before-SL)={p_buy:.3f} P(SELL TP-before-SL)={p_sell:.3f}",
    }


def run_loop(
    model_buy_path: str,
    model_sell_path: str,
    symbol: str,
    timeframe: str,
    lookback_bars: int,
    poll_seconds: int,
    higher_timeframe: str | None = None,
    higher_lookback_bars: int = 300,
    buy_threshold: float = BUY_THRESHOLD,
    sell_threshold: float = SELL_THRESHOLD,
    news_store_path: str | None = None,
) -> None:
    model_buy = lgb.Booster(model_file=model_buy_path)
    model_sell = lgb.Booster(model_file=model_sell_path)
    connect()
    try:
        while True:
            try:
                signal = latest_signal(
                    model_buy, model_sell, symbol, timeframe, lookback_bars,
                    higher_timeframe, higher_lookback_bars, buy_threshold, sell_threshold,
                    news_store_path=news_store_path,
                )
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
    parser.add_argument("--model-buy", default="kronos_model_buy.txt", help="Model trained with train.py --side BUY.")
    parser.add_argument("--model-sell", default="kronos_model_sell.txt", help="Model trained with train.py --side SELL.")
    parser.add_argument("--symbol", default="XAUUSDm")
    parser.add_argument("--timeframe", default="M5")
    parser.add_argument(
        "--higher-timeframe",
        default=None,
        help="Must match whatever --higher-timeframe train.py used for both models, or omit if it used none.",
    )
    parser.add_argument(
        "--lookback-bars",
        type=int,
        default=300,
        help="Recent bars to fetch each cycle — only needs enough for the slowest indicator (EMA 200) to warm up, not the full training history.",
    )
    parser.add_argument(
        "--higher-lookback-bars",
        type=int,
        default=300,
        help="Same idea as --lookback-bars, for the higher timeframe (only used if --higher-timeframe is set).",
    )
    parser.add_argument("--buy-threshold", type=float, default=BUY_THRESHOLD)
    parser.add_argument("--sell-threshold", type=float, default=SELL_THRESHOLD)
    parser.add_argument(
        "--news-store",
        default=None,
        help="Path to a news/store.py JSONL article file (see collect_news.py) - only pass this if BOTH "
        "models were trained with train.py --news-store using the same path's history.",
    )
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()
    run_loop(
        args.model_buy,
        args.model_sell,
        args.symbol,
        args.timeframe,
        args.lookback_bars,
        args.poll_seconds,
        args.higher_timeframe,
        args.higher_lookback_bars,
        args.buy_threshold,
        args.sell_threshold,
        news_store_path=args.news_store,
    )


if __name__ == "__main__":
    main()
