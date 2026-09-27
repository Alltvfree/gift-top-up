"""Chronological walk-forward window generation (Phase 3).

Deliberately NOT a single random train/test split (that's train.py's job,
for a quick first checkpoint) — this rolls a train/validation/test triplet
forward through calendar time, refusing to let any window's test period be
anything other than data strictly after everything used to build its model.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Window:
    index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


def generate_windows(
    data_start: pd.Timestamp,
    data_end: pd.Timestamp,
    train_days: int,
    validation_days: int,
    test_days: int,
    step_days: int,
    embargo_minutes: int = 0,
) -> list[Window]:
    """Roll [train][embargo][validation][embargo][test] forward by
    step_days until test_end would exceed data_end. Each window's pieces
    are strictly ordered and non-overlapping (the embargo carves out a gap
    rather than letting train/validation/test touch), so no window can see
    a single minute of its own future."""
    if train_days <= 0 or validation_days <= 0 or test_days <= 0 or step_days <= 0:
        raise ValueError("train_days, validation_days, test_days, step_days must all be positive.")

    embargo = pd.Timedelta(minutes=embargo_minutes)
    windows: list[Window] = []
    train_start = data_start
    idx = 0
    while True:
        train_end = train_start + pd.Timedelta(days=train_days)
        val_start = train_end + embargo
        val_end = val_start + pd.Timedelta(days=validation_days)
        test_start = val_end + embargo
        test_end = test_start + pd.Timedelta(days=test_days)
        if test_end > data_end:
            break
        windows.append(
            Window(idx, train_start, train_end, val_start, val_end, test_start, test_end)
        )
        train_start = train_start + pd.Timedelta(days=step_days)
        idx += 1
    return windows
