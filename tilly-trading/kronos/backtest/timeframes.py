"""A small MT5-free copy of mt5_data.TIMEFRAME_MINUTES, so the analytics
side of the backtester (walk_forward.py, windows.py) never has to import
mt5_data.py — same separation-of-concerns reasoning as features.py/
labels.py/train.py already follow ("no MT5 dependency, fully unit-testable
without a live terminal"). tests/test_timeframes.py asserts this stays in
sync with mt5_data.TIMEFRAME_MINUTES whenever MT5 is importable.
"""
from __future__ import annotations

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}


def bars_per_year(timeframe: str) -> float:
    minutes = TIMEFRAME_MINUTES.get(timeframe.upper())
    if minutes is None:
        raise ValueError(f"Unknown timeframe {timeframe!r}")
    return (365 * 24 * 60) / minutes
