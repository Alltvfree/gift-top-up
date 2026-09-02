"""Run a small optimization + walk-forward from the command line.

    cd xauusd-bot
    python scripts/run_optimization.py

Runs on the mock adapter's **SYNTHETIC** data. It demonstrates grid search,
walk-forward splitting and overfitting grading — it does NOT search for or claim
a profitable configuration. Never auto-deploy an optimized strategy to live
trading (spec §24).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.config import BotConfig  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.core.models import Timeframe  # noqa: E402
from app.mt5.mock_adapter import MockMT5Adapter  # noqa: E402
from app.optimization.optimizer import Optimizer, save_results  # noqa: E402
from app.optimization.walk_forward import WalkForward  # noqa: E402


def base_config() -> BotConfig:
    # Short indicators so the synthetic sample produces trades.
    return BotConfig(
        strategy={"ema_fast": 8, "ema_slow": 21, "ema_short": 8, "rsi_period": 7,
                  "atr_period": 7, "min_score": 70, "pullback_atr_mult": 30.0,
                  "rsi_overbought": 100.0, "rsi_oversold": 0.0},
        risk={"cooldown_minutes": 0, "max_daily_trades": 1000},
        stop_loss={"atr_period": 7, "atr_multiplier": 1.5},
        break_even={"enabled": False}, trailing_stop={"enabled": False},
        trading_sessions={"enabled": False},
    )


def main() -> int:
    configure_logging(level="WARNING")
    adapter = MockMT5Adapter(seed=11)
    adapter.connect()
    info = adapter.get_symbol_info("XAUUSD")
    candles = {
        Timeframe.H1: adapter.get_candles("XAUUSD", Timeframe.H1, 75),
        Timeframe.M15: adapter.get_candles("XAUUSD", Timeframe.M15, 300),
        Timeframe.M5: adapter.get_candles("XAUUSD", Timeframe.M5, 900),
    }
    grid = {"take_profit.risk_reward": [1.5, 2.0, 2.5, 3.0]}

    print("=" * 60)
    print("  GRID SEARCH  (SYNTHETIC DATA — demo only)")
    print("=" * 60)
    opt = Optimizer(base_config(), info, candles, grid,
                    objective="expectancy_r", min_trades=3)
    results = opt.run(method="grid")
    for r in results[:5]:
        print(f"  score={r.score:>8.3f}  trades={r.total_trades:>3}  "
              f"net={r.net_profit:>9.2f}  {r.params}")
    save_results(results, "data/optimization/grid_results.json")

    print("\n" + "=" * 60)
    print("  WALK-FORWARD  (train -> validation -> out-of-sample)")
    print("=" * 60)
    wf = WalkForward(base_config(), info, candles, grid,
                     train_bars=450, validation_bars=200, oos_bars=200,
                     objective="expectancy_r", min_trades=3)
    folds = wf.run(method="grid")
    for f in folds:
        print(f"  fold {f.index}: best={f.best_params}")
        print(f"    train  net={f.train.net_profit:>9.2f} pf={f.train.profit_factor}")
        print(f"    valid  net={f.validation.net_profit:>9.2f} "
              f"pf={f.validation.profit_factor}")
        print(f"    oos    net={f.out_of_sample.net_profit:>9.2f} "
              f"pf={f.out_of_sample.profit_factor}")
        print(f"    robustness: {f.overfitting.rating.value}")
        for flag in f.overfitting.flags:
            print(f"      - {flag}")

    print("\n  NOTE: synthetic data; results are meaningless for real trading.")
    print("  Do NOT auto-deploy an optimized strategy to live trading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
