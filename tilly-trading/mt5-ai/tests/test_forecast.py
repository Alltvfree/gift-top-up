import numpy as np
import pandas as pd
import pytest

from mt5_ai.forecast import KronosForecaster, summarize_paths


def _bars(n=300):
    t = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    c = 5000 + np.cumsum(np.random.default_rng(1).normal(0, 1, n))
    return pd.DataFrame({"time": t, "open": c, "high": c + 1, "low": c - 1, "close": c})


class StubPredictor:
    """Records how Kronos is called and returns scripted close paths."""

    def __init__(self, drift):
        self.drift, self.calls = drift, []

    def predict_batch(self, df_list, x_ts_list, y_ts_list, pred_len, **kw):
        self.calls.append((len(df_list), pred_len, kw, y_ts_list[0]))
        rng = np.random.default_rng(0)
        last = float(df_list[0]["close"].iloc[-1])
        outs = []
        for _ in df_list:
            close = last + self.drift * np.arange(1, pred_len + 1) + rng.normal(0, 0.5, pred_len)
            outs.append(pd.DataFrame({"close": close}, index=y_ts_list[0]))
        return outs


def test_summary_counts_the_share_of_paths_ending_higher():
    paths = np.array([[101, 102], [101, 103], [99, 98], [101, 104], [100, 106]], float)
    s = summarize_paths(100.0, pd.Timestamp("2024-01-01", tz="UTC"), pd.Timedelta(minutes=15), paths)
    assert s["samples"] == 5 and s["share_of_paths_ending_higher"] == 0.8 and s["lean"] == "up"
    assert s["final_change_pct_mean"] == pytest.approx(((102 + 103 + 98 + 104 + 106) / 5 / 100 - 1) * 100)
    assert s["forecast_until"].startswith("2024-01-01T00:30") and len(s["mean_path_close"]) == 2
    assert "Unverified signal" in s["caveat"]


def test_lean_needs_a_lopsided_vote():
    base = dict(last_time=pd.Timestamp("2024-01-01", tz="UTC"), step=pd.Timedelta(minutes=15))
    even = summarize_paths(100.0, paths=np.array([[101], [99], [101], [99]], float), **base)
    down = summarize_paths(100.0, paths=np.array([[99]] * 5, float), **base)
    assert even["lean"] == "none" and down["lean"] == "down" and down["share_of_paths_ending_higher"] == 0.0
    one = summarize_paths(100.0, paths=np.array([[101.0]]), **base)
    assert one["final_change_pct_std"] is None and one["final_close_p10"] is None


def test_forecast_runs_independent_samples_in_one_batch_and_continues_the_clock():
    pred = StubPredictor(drift=0.5)
    f = KronosForecaster("/unused", loader=lambda: pred)
    out = f.forecast(_bars(), pred_len=8, samples=6)
    n, pred_len, kw, y_ts = pred.calls[0]
    assert (n, pred_len, kw["sample_count"]) == (6, 8, 1), "N copies with sample_count=1, so draws are not averaged away"
    assert len(y_ts) == 8 and y_ts.iloc[0] == _bars()["time"].iloc[-1] + pd.Timedelta(minutes=15)
    assert out["model"] == "NeoQuasar/Kronos-mini" and out["lean"] == "up" and out["samples"] == 6


def test_context_is_clipped_to_the_models_window_and_model_loads_once():
    loads = []
    pred = StubPredictor(0.0)
    f = KronosForecaster("/unused", "small", loader=lambda: (loads.append(1), pred)[1])
    f.forecast(_bars(900), 4, 3)
    f.forecast(_bars(900), 4, 3)
    assert len(pred.calls) == 2 and loads == [1]
    assert f.max_context == 512


def test_bad_inputs():
    f = KronosForecaster("/unused", loader=lambda: StubPredictor(0))
    with pytest.raises(ValueError, match="at least 64"):
        f.forecast(_bars(40), 4, 3)
    with pytest.raises(ValueError, match="pred_len"):
        f.forecast(_bars(), 0, 3)
    with pytest.raises(ValueError, match="samples"):
        f.forecast(_bars(), 4, 99)
    with pytest.raises(ValueError, match="model_size"):
        KronosForecaster("/unused", "huge")
