"""Data-quality validation (Phase 24) — checked before a backtest run, not
silently patched. Every repair or discard is logged in the returned report
so it ends up in the HTML report's warnings section, not hidden.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class DataQualityReport:
    symbol: str
    timeframe: str
    total_rows: int
    duplicate_timestamps: int = 0
    out_of_order: int = 0
    invalid_ohlc: int = 0
    zero_or_negative_price: int = 0
    extreme_gaps: int = 0
    rows_discarded: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return (
            self.duplicate_timestamps == 0
            and self.out_of_order == 0
            and self.invalid_ohlc == 0
            and self.zero_or_negative_price == 0
        )


def validate_ohlc(
    df: pd.DataFrame, symbol: str, timeframe: str, expected_gap: pd.Timedelta | None = None
) -> tuple[pd.DataFrame, DataQualityReport]:
    """Returns (cleaned_df, report). Rows that are structurally broken
    (invalid OHLC ordering, non-positive prices, exact duplicate
    timestamps) are DISCARDED — never silently repaired by, say, averaging
    neighbors — and every discard is counted and logged. Gaps and
    out-of-order timestamps are reported but not discarded (a gap is real
    market history, e.g. a weekend close; out-of-order is fixed by
    re-sorting, which is a safe, logged, non-destructive repair)."""
    report = DataQualityReport(symbol=symbol, timeframe=timeframe, total_rows=len(df))
    out = df.copy()

    dup_mask = out["time"].duplicated(keep="first")
    report.duplicate_timestamps = int(dup_mask.sum())
    if report.duplicate_timestamps:
        report.notes.append(f"Discarded {report.duplicate_timestamps} duplicate-timestamp rows.")
        out = out[~dup_mask]

    sorted_time = out["time"].is_monotonic_increasing
    report.out_of_order = 0 if sorted_time else int((out["time"].diff().dt.total_seconds() < 0).sum())
    if not sorted_time:
        report.notes.append(f"Re-sorted {report.out_of_order} out-of-order rows by time.")
        out = out.sort_values("time").reset_index(drop=True)

    non_positive = (out[["open", "high", "low", "close"]] <= 0).any(axis=1)
    report.zero_or_negative_price = int(non_positive.sum())

    bad_ohlc = (
        (out["high"] < out["low"])
        | (out["high"] < out["open"])
        | (out["high"] < out["close"])
        | (out["low"] > out["open"])
        | (out["low"] > out["close"])
    )
    report.invalid_ohlc = int(bad_ohlc.sum())

    discard_mask = non_positive | bad_ohlc
    if discard_mask.any():
        report.notes.append(
            f"Discarded {int(discard_mask.sum())} rows with invalid OHLC ordering or non-positive prices."
        )
        out = out[~discard_mask].reset_index(drop=True)

    if expected_gap is not None and len(out) > 1:
        gaps = out["time"].diff().dropna()
        extreme = gaps > expected_gap * 5
        report.extreme_gaps = int(extreme.sum())
        if report.extreme_gaps:
            report.notes.append(
                f"{report.extreme_gaps} gap(s) wider than 5x the expected bar interval "
                "(market closures/holidays are expected here; investigate if unexpected)."
            )

    report.rows_discarded = report.total_rows - len(out)
    return out.reset_index(drop=True), report
