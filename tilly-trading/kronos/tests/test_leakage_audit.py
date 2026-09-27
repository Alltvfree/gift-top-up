import pandas as pd

from backtest.leakage_audit import LookaheadError, audit_merge, build_audit_table, verify_higher_timeframe_alignment
from conftest import make_synthetic_ohlc
from features import compute_features


def _base_and_aligned_higher():
    # Deriving `higher` FROM `base` (every 12th M5 bar = 1-hour spacing)
    # guarantees real time overlap between the two series — same technique
    # tests/test_features.py's own merge check already uses. Two
    # independently-generated synthetic series almost never overlap in
    # time at all, which would make every base row match on the higher
    # series' very last (necessarily long-closed) bar — a scenario that
    # can never expose a still-forming-bar bug regardless of whether the
    # merge is correct or broken.
    base = make_synthetic_ohlc(2000, freq="5min")
    higher = base.iloc[::12].reset_index(drop=True).copy()
    return base, higher


def test_correct_merge_passes_the_audit():
    base, higher = _base_and_aligned_higher()
    base_feats = compute_features(base)
    higher_feats = compute_features(higher)
    merged = audit_merge(base_feats, higher_feats, prefix="htf")
    verify_higher_timeframe_alignment(merged, higher, "htf")  # must not raise


def test_still_forming_bar_is_caught_by_the_audit(monkeypatch):
    """Reconstructs the exact bug this project already found and fixed once
    (see README) — a naive merge_asof on raw OPEN timestamps attaches a
    higher-timeframe bar that hasn't closed yet. The audit must catch this
    independently of merge_higher_timeframe's own (already fixed) logic."""
    import features

    def broken_merge(base, higher, prefix):
        h = higher.add_prefix(f"{prefix}_").rename(columns={f"{prefix}_time": "time"})
        return pd.merge_asof(base.sort_values("time"), h.sort_values("time"), on="time", direction="backward")

    monkeypatch.setattr(features, "merge_higher_timeframe", broken_merge)

    base, higher = _base_and_aligned_higher()
    base_feats = compute_features(base)
    higher_feats = compute_features(higher)
    merged = audit_merge(base_feats, higher_feats, prefix="htf")

    try:
        verify_higher_timeframe_alignment(merged, higher, "htf")
        assert False, "expected LookaheadError for a naive open-time-only merge"
    except LookaheadError:
        pass


def test_audit_requires_the_probe_column():
    base, higher = _base_and_aligned_higher()
    try:
        verify_higher_timeframe_alignment(base, higher, "htf")  # no probe column at all
        assert False, "expected ValueError when the merged frame lacks the probe column"
    except ValueError:
        pass


def test_audit_table_has_no_lookahead_marked_ok_for_every_checked_category():
    entries = build_audit_table(has_higher_timeframe=True)
    assert len(entries) > 0
    for e in entries:
        assert e.status in ("OK", "N/A", "WARNING")
        assert e.detail  # every entry must document ITS OWN reasoning, not a placeholder
