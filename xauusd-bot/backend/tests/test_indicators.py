"""Tests for technical indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.indicators.indicators import atr, ema, rsi, sma, true_range


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = sma(s, 3)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx(3.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_ema_constant_series_equals_constant():
    s = pd.Series([5.0] * 50)
    result = ema(s, 10)
    assert result.iloc[-1] == pytest.approx(5.0)


def test_ema_recursive_definition():
    # EMA(adjust=False): e_t = alpha*x_t + (1-alpha)*e_{t-1}, seeded by SMA warmup.
    s = pd.Series(np.arange(1, 21, dtype=float))
    period = 5
    result = ema(s, period)
    alpha = 2.0 / (period + 1)
    # Recompute the last step manually from the previous EMA value.
    expected_last = alpha * s.iloc[-1] + (1 - alpha) * result.iloc[-2]
    assert result.iloc[-1] == pytest.approx(expected_last)


def test_rsi_all_gains_is_100():
    s = pd.Series(np.arange(1, 40, dtype=float))  # strictly increasing
    result = rsi(s, 14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_all_losses_is_zero():
    s = pd.Series(np.arange(40, 1, -1, dtype=float))  # strictly decreasing
    result = rsi(s, 14)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_rsi_bounds_and_warmup():
    rng = np.random.default_rng(0)
    s = pd.Series(np.cumsum(rng.normal(size=200)) + 100)
    result = rsi(s, 14)
    valid = result.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()
    # Warm-up region should be NaN.
    assert result.iloc[:14].isna().all()


def test_true_range_matches_manual():
    high = pd.Series([10.0, 11.0, 12.0])
    low = pd.Series([9.0, 9.5, 11.0])
    close = pd.Series([9.5, 10.5, 11.5])
    tr = true_range(high, low, close)
    # First row: only high-low (no prev close) = 1.0
    assert tr.iloc[0] == pytest.approx(1.0)
    # Second row: max(11-9.5, |11-9.5|, |9.5-9.5|) = max(1.5,1.5,0)=1.5
    assert tr.iloc[1] == pytest.approx(1.5)


def test_atr_positive_and_warmup():
    rng = np.random.default_rng(1)
    close = pd.Series(np.cumsum(rng.normal(size=100)) + 2000)
    high = close + rng.uniform(0.1, 1.0, size=100)
    low = close - rng.uniform(0.1, 1.0, size=100)
    result = atr(high, low, close, 14)
    valid = result.dropna()
    assert (valid > 0).all()
    # TR is valid from index 0 (high-low), so with min_periods=14 the first ATR
    # value appears at index 13; indices 0..12 are the warm-up window.
    assert result.iloc[:13].isna().all()
    assert not np.isnan(result.iloc[13])


def test_invalid_period_raises():
    s = pd.Series([1.0, 2.0, 3.0])
    for bad in (0, -1):
        with pytest.raises(ValueError):
            ema(s, bad)
        with pytest.raises(ValueError):
            rsi(s, bad)
