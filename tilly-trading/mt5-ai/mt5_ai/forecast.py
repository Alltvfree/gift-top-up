"""Kronos foundation-model forecasting on live MT5 candles
(github.com/shiyu-coder/Kronos, MIT).

One forecast = `samples` independent sampled price paths, run in a single
batched call. Kronos is generative: each path is a draw, so the useful
output is the DISTRIBUTION (what share of paths end higher, how spread out
they are), not one line. The share is an uncalibrated vote count, not a
probability — kronos_eval.py exists to measure how often it was right on the
symbol you trade, and nothing here should be trusted before that.
"""
from __future__ import annotations

import sys
import threading
from typing import Callable

import numpy as np
import pandas as pd

# (tokenizer, model, max_context) — from the Kronos README's model zoo.
MODEL_ZOO = {
    "mini": ("NeoQuasar/Kronos-Tokenizer-2k", "NeoQuasar/Kronos-mini", 2048),
    "small": ("NeoQuasar/Kronos-Tokenizer-base", "NeoQuasar/Kronos-small", 512),
    "base": ("NeoQuasar/Kronos-Tokenizer-base", "NeoQuasar/Kronos-base", 512),
}

CAVEAT = (
    "Unverified signal. The 'share ending higher' is a vote count over sampled paths, not a calibrated probability; "
    "run kronos_eval on this symbol/timeframe to see how often the lean has actually been right."
)


def summarize_paths(last_close: float, last_time: pd.Timestamp, step: pd.Timedelta, paths: np.ndarray) -> dict:
    """paths: (samples, horizon) array of forecast CLOSE prices."""
    paths = np.asarray(paths, dtype=float)
    n, horizon = paths.shape
    final = paths[:, -1]
    change_pct = (final / last_close - 1.0) * 100.0
    p_up = float((final > last_close).mean())
    mean_path = paths.mean(axis=0)
    lean = "up" if p_up >= 0.8 else "down" if p_up <= 0.2 else "none"
    return {
        "samples": n,
        "horizon_bars": horizon,
        "last_close": round(float(last_close), 5),
        "last_bar_time": last_time.isoformat(),
        "forecast_until": (last_time + step * horizon).isoformat(),
        "share_of_paths_ending_higher": round(p_up, 3),
        "share_stderr": round(float(np.sqrt(p_up * (1 - p_up) / n)), 3),
        "lean": lean,
        "final_change_pct_mean": round(float(change_pct.mean()), 4),
        "final_change_pct_std": round(float(change_pct.std(ddof=1)), 4) if n > 1 else None,
        "final_close_p10": round(float(np.quantile(final, 0.10)), 5) if n >= 5 else None,
        "final_close_p90": round(float(np.quantile(final, 0.90)), 5) if n >= 5 else None,
        "mean_path_close": [round(float(v), 5) for v in mean_path],
        "caveat": CAVEAT,
    }


class KronosForecaster:
    def __init__(self, repo_dir: str, model_size: str = "mini", *, loader: Callable | None = None):
        if model_size not in MODEL_ZOO:
            raise ValueError(f"model_size must be one of {sorted(MODEL_ZOO)}")
        self.repo_dir, self.model_size = repo_dir, model_size
        self._loader = loader
        self._predictor = None
        self._lock = threading.Lock()

    def _load(self):
        """Loaded once, on first use: importing torch and downloading weights is slow."""
        with self._lock:
            if self._predictor is None:
                if self._loader is not None:
                    self._predictor = self._loader()
                else:
                    if self.repo_dir not in sys.path:
                        sys.path.insert(0, self.repo_dir)
                    from model import Kronos, KronosPredictor, KronosTokenizer  # Kronos' own package

                    tok_name, model_name, max_context = MODEL_ZOO[self.model_size]
                    self._predictor = KronosPredictor(
                        Kronos.from_pretrained(model_name), KronosTokenizer.from_pretrained(tok_name), max_context=max_context
                    )
            return self._predictor

    @property
    def max_context(self) -> int:
        return MODEL_ZOO[self.model_size][2]

    def forecast(self, df: pd.DataFrame, pred_len: int, samples: int) -> dict:
        """df: closed bars with time/open/high/low/close, oldest first."""
        if not 1 <= pred_len <= 200 or not 1 <= samples <= 30:
            raise ValueError("pred_len must be 1..200 and samples 1..30.")
        if len(df) < 64:
            raise ValueError(f"Kronos needs at least 64 bars of context, got {len(df)}.")
        df = df.tail(self.max_context).reset_index(drop=True)
        x_ts = df["time"].reset_index(drop=True)
        step = x_ts.diff().dropna().median()
        y_ts = pd.Series(pd.date_range(x_ts.iloc[-1] + step, periods=pred_len, freq=step))
        x_df = df[["open", "high", "low", "close"]]

        predictor = self._load()
        # The same history repeated `samples` times with sample_count=1: N independent
        # draws in ONE batched pass (sample_count>1 would average them away).
        outs = predictor.predict_batch(
            [x_df] * samples, [x_ts] * samples, [y_ts] * samples,
            pred_len=pred_len, T=1.0, top_p=0.9, sample_count=1, verbose=False,
        )
        paths = np.stack([o["close"].to_numpy(float) for o in outs])
        return {"model": MODEL_ZOO[self.model_size][1], **summarize_paths(float(df["close"].iloc[-1]), x_ts.iloc[-1], step, paths)}
