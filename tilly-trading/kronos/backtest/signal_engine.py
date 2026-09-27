"""Probability -> BUY/SELL/NO_TRADE (Phase 5).

Separate from infer.py's live BUY_THRESHOLD/SELL_THRESHOLD constants
deliberately — the backtester's thresholds are config-driven per Phase 21
("do not hardcode strategy parameters"), whereas infer.py's live thresholds
are a separate, already-shipped concern. If the backtest settles on better
thresholds than infer.py's current 0.60/0.40, that's a follow-up change to
propose there explicitly, not something this module reaches into silently.
"""
from __future__ import annotations

from .config import SignalConfig


def decide_side(probability: float, cfg: SignalConfig) -> str:
    if probability >= cfg.buy_threshold:
        return "BUY"
    if probability <= cfg.sell_threshold:
        return "SELL"
    return "NO_TRADE"
