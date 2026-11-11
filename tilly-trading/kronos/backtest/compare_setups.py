"""Scores every candidate setup in setups/library.py (plus the trend-pullback
setup when a higher timeframe is given) with the SAME simulator, costs, risk
rules and verdict gate, then tests whether requiring agreement between them
beats the best single member.

  python -m backtest.compare_setups --config config/setup_xauusd.toml --symbol XAUUSD
  python -m backtest.compare_setups --base-csv m15.csv --higher-csv h1.csv

Each strategy is also scored against a NULL: its own signals shifted by random
amounts in time (same frequency, same stop/target geometry, no relationship to
the market). A strategy whose real expectancy isn't clearly above its null is
trading noise with a nice story attached.

Nothing here tunes anything. If you change a strategy's rules after seeing
this table, the table no longer applies to it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from setups.library import STRATEGIES, confluence  # noqa: E402

from .account import Account  # noqa: E402
from .config import BacktestConfig, load_config  # noqa: E402
from .data_quality import validate_ohlc  # noqa: E402
from .setup_backtest import WARMUP_BARS, _load_csv, sanitize_spread  # noqa: E402
from .setup_stats import MIN_TRADES_FOR_VERDICT, add_r_multiple, edge_stats, verdict  # noqa: E402
from .simulator import run_simulation, trades_to_frame  # noqa: E402
from .symbols import SymbolSpec, from_mt5, get_symbol_spec  # noqa: E402
from .timeframes import TIMEFRAME_MINUTES  # noqa: E402

SIGNAL_COLS = ["setup_buy", "setup_sell", "signal_sl_distance", "signal_tp_distance",
               "predicted_probability_buy", "predicted_probability_sell"]


def score(frame: pd.DataFrame, cfg: BacktestConfig, spec: SymbolSpec, min_trades: int) -> dict:
    sim_df = frame.iloc[WARMUP_BARS:].reset_index(drop=True)
    account = Account(cfg.initial_balance, cfg.currency)
    trades = run_simulation(sim_df, cfg, spec, account, window_index=0)
    tdf = trades_to_frame(trades)
    fired = int((sim_df["setup_buy"] | sim_df["setup_sell"]).sum())
    if tdf.empty:
        return {"signals": fired, "trades": 0, "verdict": verdict({"trades": 0}, 0.0, min_trades)}
    tdf = add_r_multiple(tdf, spec)
    st = edge_stats(tdf, seed=cfg.random_seed)
    st["signals"] = fired
    st["net_profit"] = float(tdf["net_pnl"].sum())
    st["verdict"] = verdict(st, st["net_profit"], min_trades)
    return st


def shifted_null(frame: pd.DataFrame, shift: int) -> pd.DataFrame:
    """Same signals, rolled `shift` bars: identical count and geometry, no link to price."""
    out = frame.copy()
    for c in SIGNAL_COLS:
        out[c] = np.roll(frame[c].to_numpy(), shift)
    return out


def null_expectancy(frame, cfg, spec, n_null: int, seed: int) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_null):
        r = score(shifted_null(frame, int(rng.integers(500, max(501, len(frame) - 500)))), cfg, spec, 10**9)
        if r.get("trades"):
            vals.append(r["expectancy_r"])
    return (float(np.mean(vals)), float(np.std(vals))) if vals else (float("nan"), float("nan"))


def compare(base_raw: pd.DataFrame, higher_raw: pd.DataFrame | None, cfg: BacktestConfig, spec: SymbolSpec,
            min_trades: int = MIN_TRADES_FOR_VERDICT, n_null: int = 5) -> pd.DataFrame:
    if cfg.spread.mode == "historical":
        base_raw, _ = sanitize_spread(base_raw)
    base_raw = base_raw.reset_index(drop=True)

    frames: dict[str, pd.DataFrame] = {name: fn(base_raw, spec.point) for name, fn in STRATEGIES.items()}
    if higher_raw is not None:
        from .setup_backtest import build_signal_frame
        from setups.trend_pullback import load_setup_params

        frames["trend_pullback"] = build_signal_frame(base_raw, higher_raw, load_setup_params(None), spec)

    rows, results = [], {}
    names = list(frames)
    combos = {f"agree2({a}+{b})": confluence({a: frames[a], b: frames[b]}) for i, a in enumerate(names) for b in names[i + 1:]}
    if len(names) >= 3:
        combos["agree2(all)"] = confluence(frames, min_agree=2)
        combos["agree3(all)"] = confluence(frames, min_agree=3)
    for label, frame in {**frames, **combos}.items():
        r = score(frame, cfg, spec, min_trades)
        if r.get("trades"):
            mu, sd = null_expectancy(frame, cfg, spec, n_null, cfg.random_seed) if n_null else (float("nan"), float("nan"))
            r["null_expectancy_r"], r["null_sd"] = mu, sd
        results[label] = r
        rows.append({
            "setup": label, "signals": r.get("signals", 0), "trades": r.get("trades", 0),
            "win_rate": r.get("win_rate"), "expectancy_r": r.get("expectancy_r"),
            "ci_low": r.get("expectancy_r_ci95_low"), "ci_high": r.get("expectancy_r_ci95_high"),
            "null_expectancy_r": r.get("null_expectancy_r"), "verdict": r["verdict"].split(" — ")[0],
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config/setup_xauusd.toml")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--bars", type=int, default=50000)
    ap.add_argument("--min-trades", type=int, default=MIN_TRADES_FOR_VERDICT)
    ap.add_argument("--null", type=int, default=5, help="Time-shifted null runs per setup (0 = skip).")
    ap.add_argument("--spec-from-mt5", action="store_true")
    ap.add_argument("--base-csv", default=None)
    ap.add_argument("--higher-csv", default=None)
    ap.add_argument("--out", default="reports/compare_setups.csv")
    a = ap.parse_args()

    cfg = load_config(a.config)
    if a.symbol:
        cfg.symbol = a.symbol
    spec = from_mt5(cfg.symbol) if a.spec_from_mt5 else get_symbol_spec(cfg.symbol)

    if a.base_csv:
        base_raw = _load_csv(a.base_csv)
        higher_raw = _load_csv(a.higher_csv) if a.higher_csv else None
    else:
        from bars import closed_bars_only
        from mt5_data import bars_to_cover_same_span, connect, disconnect, download_history, server_time_now

        connect()
        try:
            base_raw = download_history(cfg.symbol, cfg.timeframe, a.bars)
            higher_raw = download_history(cfg.symbol, cfg.higher_timeframe,
                                          bars_to_cover_same_span(cfg.timeframe, a.bars, cfg.higher_timeframe))
            now = server_time_now(cfg.symbol)
            base_raw = closed_bars_only(base_raw, TIMEFRAME_MINUTES[cfg.timeframe.upper()], now)
            higher_raw = closed_bars_only(higher_raw, TIMEFRAME_MINUTES[cfg.higher_timeframe.upper()], now)
        finally:
            disconnect()

    gap = pd.Timedelta(minutes=TIMEFRAME_MINUTES[cfg.timeframe.upper()])
    base_raw, _ = validate_ohlc(base_raw, cfg.symbol, cfg.timeframe, gap)
    if higher_raw is not None:
        higher_raw, _ = validate_ohlc(higher_raw, cfg.symbol, cfg.higher_timeframe)

    table = compare(base_raw, higher_raw, cfg, spec, a.min_trades, a.null)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(a.out, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:+.3f}".format):
        print(table.to_string(index=False))
    print(f"\nWritten to {a.out}")
    print("Read this honestly: a row is only interesting if its verdict is POSITIVE EXPECTANCY SUPPORTED, "
          "its CI is above zero AND it sits clearly above its own null. With ~10 rows, one 'good' row is expected by chance.")


if __name__ == "__main__":
    main()
