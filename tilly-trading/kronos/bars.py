"""Pure helpers for live bars — no MT5 import, so unit-testable anywhere."""
from __future__ import annotations

import pandas as pd


def closed_bars_only(df: pd.DataFrame, bar_minutes: int, now: pd.Timestamp) -> pd.DataFrame:
    """Drop any bar that has not finished forming as of `now`.

    MT5's copy_rates_from_pos(..., start_pos=0, ...) includes the CURRENT,
    still-forming bar as its last row, and mt5_data labels every bar by its
    OPEN time. A live decision made from that row would read a half-built
    candle — wrong body/wick/close/high/low versus what the same bar looks
    like once closed, which is what every backtest saw. A bar is closed once
    open time + its duration <= now; `now` must be in the SAME clock as the
    bar times (the broker's server time — see mt5_data.server_time_now), not
    the PC's own clock.
    """
    close_time = df["time"] + pd.Timedelta(minutes=bar_minutes)
    return df[close_time <= now].reset_index(drop=True)
