"""Leakage audit (Phase 2) — a runtime guard plus a documented table for
the report.

The unit tests (tests/test_leakage_audit.py, tests/test_features.py)
already prove no-lookahead against synthetic data. This module is the
defense-in-depth counterpart that runs against REAL data on every actual
backtest: audit_merge() re-merges the higher timeframe onto the base with
an explicit `<prefix>_open_time` probe column carried through (the exact
technique tests/test_features.py's own no-lookahead check already uses),
and verify_higher_timeframe_alignment() then checks every attached bar's
close time (open_time + duration) is <= the base row's own time — the exact
bug this project already found and fixed once (see README's multi-timeframe
story) shouldn't be able to silently reappear.

Why not independently re-derive the match instead of probing it: a
backward-asof match on open time alone will always find *some* bar whose
open is at or before the base row's time — including the currently-forming
one — so recomputing that match independently and checking ITS close time
proves nothing about what the real merge actually attached (it can't tell
a correctly-shifted merge from a naive one; both would "find" a bar). The
probe column instead asks what merge_higher_timeframe genuinely picked.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


class LookaheadError(RuntimeError):
    pass


def audit_merge(base_feats: pd.DataFrame, higher_feats: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Runs the real features.merge_higher_timeframe, with the higher
    frame's own open time carried through under `<prefix>_open_time` so the
    result can be independently checked afterward."""
    from features import merge_higher_timeframe  # noqa: PLC0415 - avoid a hard import cycle at module load

    probed = higher_feats.copy()
    probed["open_time"] = probed["time"]
    return merge_higher_timeframe(base_feats, probed, prefix=prefix)


def verify_higher_timeframe_alignment(merged: pd.DataFrame, higher_raw: pd.DataFrame, prefix: str) -> None:
    """merged: the output of audit_merge() above — must carry a
    `<prefix>_open_time` probe column. Asserts every attached bar's close
    time (open_time + duration) is <= the base row's own time."""
    probe_col = f"{prefix}_open_time"
    if probe_col not in merged.columns:
        raise ValueError(
            f"verify_higher_timeframe_alignment expects a {probe_col!r} probe column — "
            "build `merged` with leakage_audit.audit_merge(), not merge_higher_timeframe() directly."
        )
    if len(higher_raw) < 2:
        raise LookaheadError("Need at least 2 higher-timeframe rows to audit bar duration.")
    bar_duration = higher_raw["time"].diff().median()

    close_time = merged[probe_col] + bar_duration
    known = merged[probe_col].notna()
    violations = merged.loc[known & (close_time > merged["time"])]
    if len(violations):
        raise LookaheadError(
            f"LOOKAHEAD: {len(violations)} row(s) matched a higher-timeframe ({prefix}) bar "
            "that had not closed yet as of the base row's own time."
        )


@dataclass
class LeakageAuditEntry:
    category: str
    status: str  # "OK" | "N/A" | "WARNING"
    detail: str


def build_audit_table(has_higher_timeframe: bool) -> list[LeakageAuditEntry]:
    """A documented, human-readable table for the HTML report (Phase 2's
    "document every leakage-sensitive operation"). Each entry names the
    actual code path responsible, not a generic claim."""
    entries = [
        LeakageAuditEntry(
            "Rolling indicators (EMA/RSI/MACD/ATR/Bollinger/ADX/stochastic)",
            "OK",
            "features.py uses only .ewm()/.rolling()/.diff()/.shift() with no negative "
            "shifts — every value at row i is a function of rows <= i (see features.py "
            "module docstring's no-lookahead guarantee, verified by tests/test_features.py).",
        ),
        LeakageAuditEntry(
            "Market structure (swing highs/lows, support/resistance, breakouts)",
            "OK",
            "features._market_structure() only confirms a swing at position i once "
            "SWING_LAG bars have passed on both sides — the most recent SWING_LAG bars' "
            "swing status is genuinely unconfirmed, matching what a live system could "
            "actually know at that bar.",
        ),
        LeakageAuditEntry(
            "Higher-timeframe features (H1 context on an M5 base)",
            "OK" if has_higher_timeframe else "N/A",
            "features.merge_higher_timeframe() shifts the higher frame's match key forward "
            "by its own bar duration before merging, so only already-CLOSED higher-timeframe "
            "bars attach. verify_higher_timeframe_alignment() re-checks this independently on "
            "every backtest run (this audit), not just in the unit tests. This is the exact "
            "bug this project caught and fixed once already (0.77 -> 0.53 AUC) — see README."
            if has_higher_timeframe
            else "This run didn't use a higher timeframe.",
        ),
        LeakageAuditEntry(
            "Target/label generation (TP-before-SL)",
            "OK",
            "labels.py is the one file explicitly allowed to look forward — it walks bars "
            "i+1..i+max_bars_forward to score the outcome. Features for row i never see this; "
            "prepare_dataset() computes features and labels independently and only joins them "
            "by position after both are done.",
        ),
        LeakageAuditEntry(
            "Train/validation/test split",
            "OK",
            "windows.py generates purely chronological, non-overlapping "
            "[train][embargo][validation][embargo][test] windows (walk_forward.py). No random "
            "shuffling anywhere in this pipeline.",
        ),
        LeakageAuditEntry(
            "Hyperparameter/threshold/TP/SL tuning",
            "OK",
            "walk_forward.py trains and early-stops using only the train/validation split; the "
            "test split's predictions are generated once, after training is frozen, and never "
            "fed back into any tuning decision for that window.",
        ),
        LeakageAuditEntry(
            "Feature scaling/normalization",
            "N/A",
            "LightGBM is a tree-based model — it splits on raw feature values and is invariant "
            "to monotonic rescaling, so there is no fitted scaler to leak train-set statistics "
            "into validation/test in the first place. (Distances are already expressed as "
            "percentages in features.py, which is about cross-symbol comparability, not scaling.)",
        ),
        LeakageAuditEntry(
            "Missing-value handling",
            "OK",
            "prepare_dataset() drops rows with any NaN feature/label rather than imputing — "
            "an imputed value computed from the full dataset (e.g. a column mean) would leak "
            "future statistics into early rows; dropping avoids that question entirely.",
        ),
        LeakageAuditEntry(
            "Execution timing (signal -> entry)",
            "OK",
            "simulator.py enters at the NEXT bar's open when execution.next_bar=True (the "
            "default) — a signal computed from bar T's close can only be acted on starting "
            "bar T+1, never bar T's own close.",
        ),
    ]
    return entries
