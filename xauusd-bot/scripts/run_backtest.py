"""Run a backtest from the command line.

    cd xauusd-bot
    python scripts/run_backtest.py

By default it runs on the mock adapter's **SYNTHETIC** data so it works with no
MT5 terminal. This is a mechanics demo, NOT a profitability claim — synthetic
random data says nothing about real performance. Point it at real historical
candles to get a meaningful result.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `app` importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.config import load_config  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.core.models import Timeframe  # noqa: E402
from app.backtesting.engine import Backtester  # noqa: E402
from app.backtesting.metrics import compute_metrics  # noqa: E402
from app.backtesting.report import export_json, export_trades_csv  # noqa: E402
from app.mt5.mock_adapter import MockMT5Adapter  # noqa: E402
from app.strategies.factory import create_strategy  # noqa: E402


def main() -> int:
    configure_logging(level="WARNING")  # keep the report readable
    config = load_config()

    # Synthetic, time-aligned candle spans (same end time per timeframe).
    adapter = MockMT5Adapter(seed=7)
    adapter.connect()
    symbol_info = adapter.get_symbol_info("XAUUSD")
    candles = {
        Timeframe.H1: adapter.get_candles("XAUUSD", Timeframe.H1, 300),
        Timeframe.M15: adapter.get_candles("XAUUSD", Timeframe.M15, 1200),
        Timeframe.M5: adapter.get_candles("XAUUSD", Timeframe.M5, 3600),
    }

    bt = Backtester(config, create_strategy(config), symbol_info, candles,
                    starting_balance=10_000, commission_per_lot=3.0,
                    slippage_points=5.0)
    result = bt.run()
    metrics = compute_metrics(result)

    print("=" * 60)
    print("  XAUUSD BACKTEST  (SYNTHETIC DATA — mechanics demo only)")
    print("=" * 60)
    print(f"  Strategy        : {result.strategy} v{result.strategy_version}")
    print(f"  Bars processed  : {result.bars_processed}")
    print(f"  Starting balance: {result.starting_balance:,.2f}")
    print(f"  Ending balance  : {result.ending_balance:,.2f}")
    print(f"  Net profit      : {result.net_profit:,.2f}")
    print("-" * 60)
    for key, value in metrics.to_dict().items():
        print(f"  {key:<24}: {value}")
    print("=" * 60)

    out = Path("data/backtests")
    export_json(result, out / "last_report.json")
    export_trades_csv(result, out / "last_trades.csv")
    print(f"  Report written to {out}/last_report.json")
    print("\n  DISCLAIMER: synthetic data. Past/simulated performance does not")
    print("  predict future results. Validate on real data + demo before live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
