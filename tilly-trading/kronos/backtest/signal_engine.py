"""Two independent probabilities -> BUY/SELL/NO_TRADE (Phase 5).

Deliberately NOT "SELL when P(BUY) is low" — that was the pre-existing
shortcut in infer.py's live inference (SELL_THRESHOLD = 1 - BUY_THRESHOLD),
inherited unexamined into the first version of this backtester too, and a
real BTCUSDm walk-forward run exposed it: 641 of 643 trades came out SELL
because the model was only ever trained on BUY-side outcomes, and "the
market probably won't let a BUY win" is not the same claim as "a SELL will
win" — those need two different labeled outcomes to be a real prediction
at all (see labels.label_tp_before_sl, which support side="BUY" and
side="SELL" as two separate targets). This module takes each side's own
probability from its own trained model and decides independently.
"""
from __future__ import annotations

from .config import SignalConfig


def decide_side(prob_buy: float, prob_sell: float, cfg: SignalConfig) -> str:
    buy_signal = cfg.trade_buy and prob_buy >= cfg.buy_threshold
    sell_signal = cfg.trade_sell and prob_sell >= cfg.sell_threshold
    if buy_signal and sell_signal:
        # Both models independently confident, in opposite directions — a
        # genuine conflict (possible: they're different questions, not
        # complements), not something to break a tie on. Sit out.
        return "NO_TRADE"
    if buy_signal:
        return "BUY"
    if sell_signal:
        return "SELL"
    return "NO_TRADE"
