"""Does Kronos actually predict THIS symbol? Run it over the past and count.

    python -m mt5_ai.kronos_eval --symbol XAUUSD --timeframe M15 --windows 40 --pred-len 8 --samples 5

Walks back through recent history in non-overlapping windows; at each one it
forecasts from the bars before the window and compares the predicted direction
to what price then did. Reports the hit rate with a confidence interval,
whether the lean's own conviction means anything, and skill versus the naive
"price stays put" forecast. Takes a few minutes on CPU (windows x samples).

It is a quick read on recent history, not a proof: a hit rate whose interval
includes 50% means no demonstrated skill, whatever the point estimate says.
"""
from __future__ import annotations

import argparse
import json
import math
import os

import numpy as np
import pandas as pd


def make_windows(n_bars: int, lookback: int, pred_len: int, windows: int) -> list[tuple[int, int, int]]:
    """(context_start, split, end) index triples, newest last, whose truth
    segments [split, end) never overlap each other."""
    out = []
    end = n_bars
    for _ in range(windows):
        split = end - pred_len
        start = split - lookback
        if start < 0:
            break
        out.append((start, split, end))
        end = split
    return out[::-1]


def wilson_interval(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


def score(pred_change_pct: list[float], actual_change_pct: list[float], p_up: list[float]) -> dict:
    pred, actual, p = (np.asarray(a, float) for a in (pred_change_pct, actual_change_pct, p_up))
    keep = actual != 0
    pred, actual, p = pred[keep], actual[keep], p[keep]
    n = len(actual)
    if n == 0:
        return {"windows": 0, "verdict": "NO DATA"}
    hits = int((np.sign(pred) == np.sign(actual)).sum())
    lo, hi = wilson_interval(hits, n)
    mae_model, mae_naive = float(np.abs(pred - actual).mean()), float(np.abs(actual).mean())
    corr = float(np.corrcoef(pred, actual)[0, 1]) if n > 2 and pred.std() > 0 and actual.std() > 0 else float("nan")

    def lean_hit_rate(mask, up: bool):
        m = int(mask.sum())
        return {"n": m, "hit_rate": float(((actual[mask] > 0) == up).mean()) if m else None}

    out = {
        "windows": n,
        "directional_hit_rate": hits / n,
        "hit_rate_ci95": [round(lo, 3), round(hi, 3)],
        "correlation_pred_vs_actual": corr,
        "mae_model_pct": mae_model,
        "mae_naive_pct": mae_naive,
        "skill_vs_naive": 1.0 - mae_model / mae_naive if mae_naive else float("nan"),
        "strong_up_lean": lean_hit_rate(p >= 0.8, True),
        "strong_down_lean": lean_hit_rate(p <= 0.2, False),
    }
    out["verdict"] = verdict(out)
    return out


def verdict(s: dict) -> str:
    lo, hi = s["hit_rate_ci95"]
    if s["windows"] < 30:
        return f"TOO FEW WINDOWS ({s['windows']}): not enough to say anything. Use --windows 60 or more."
    if lo > 0.5:
        return "SOME DIRECTIONAL SKILL on recent history (hit-rate interval above 50%). Still one sample of the past: re-run on other periods and paper trade before trusting it."
    if hi < 0.5:
        return "WORSE THAN A COIN: the forecast direction has been wrong more often than right. Do not follow it."
    return "NO DEMONSTRATED SKILL: the hit-rate interval includes 50%, i.e. indistinguishable from guessing."


def main() -> None:
    from .broker import Mt5Broker
    from .config import Settings
    from .forecast import KronosForecaster

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--timeframe", default="M15")
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--pred-len", type=int, default=8)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--windows", type=int, default=40)
    ap.add_argument("--out", default="kronos_eval.json")
    a = ap.parse_args()

    settings = Settings.from_env()
    if not settings.kronos_repo:
        raise SystemExit("Set MT5_AI_KRONOS_REPO to the folder holding Kronos' `model` package.")
    import MetaTrader5 as mt5

    broker = Mt5Broker(mt5)
    broker.initialize(os.environ.get("MT5_AI_TERMINAL_PATH") or None)
    try:
        need = a.lookback + a.pred_len * a.windows
        bars = broker.rates(a.symbol, a.timeframe, need)
    finally:
        broker.shutdown()
    forecaster = KronosForecaster(settings.kronos_repo, settings.kronos_model)
    wins = make_windows(len(bars), a.lookback, a.pred_len, a.windows)
    print(f"{len(wins)} windows of {a.pred_len} bars from {bars['time'].iloc[0]} to {bars['time'].iloc[-1]}")

    preds, actuals, ups = [], [], []
    for i, (start, split, end) in enumerate(wins, 1):
        f = forecaster.forecast(bars.iloc[start:split], a.pred_len, a.samples)
        last = float(bars["close"].iloc[split - 1])
        actuals.append((float(bars["close"].iloc[end - 1]) / last - 1) * 100)
        preds.append(f["final_change_pct_mean"])
        ups.append(f["share_of_paths_ending_higher"])
        print(f"  {i}/{len(wins)}  predicted {preds[-1]:+.3f}%  actual {actuals[-1]:+.3f}%", flush=True)

    result = {"symbol": a.symbol, "timeframe": a.timeframe, "pred_len": a.pred_len, "samples": a.samples, **score(preds, actuals, ups)}
    with open(a.out, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
    print(f"\nVERDICT: {result['verdict']}")


if __name__ == "__main__":
    main()
