"""Headless continuous bot runner (no API/dashboard).

    cd xauusd-bot
    python scripts/run_bot.py               # PAPER, ticks every 5s
    BOT_TICK_SECONDS=2 python scripts/run_bot.py

Runs the trading engine loop directly. Honors TRADING_MODE from the environment
(default PAPER). LIVE additionally requires BOT_ALLOW_LIVE=true and, here, the
RUN_BOT_CONFIRM_LIVE=ENABLE LIVE TRADING environment variable — a deliberate
second gate so LIVE is never entered by accident.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.api.service import BotService  # noqa: E402
from app.core.logging import configure_logging, get_logger, log_event  # noqa: E402
from app.core.models import TradingMode  # noqa: E402


def main() -> int:
    configure_logging(level=os.getenv("LOG_LEVEL", "INFO"), log_dir="logs")
    log = get_logger("scripts.run_bot")
    service = BotService()

    if service.mode is TradingMode.LIVE:
        if os.getenv("RUN_BOT_CONFIRM_LIVE") != "ENABLE LIVE TRADING":
            print("=" * 64)
            print("  WARNING")
            print("  Automated trading can lose money. Past backtest")
            print("  performance does not guarantee future results.")
            print("")
            print("  LIVE TRADING requires explicit confirmation. Set:")
            print("    RUN_BOT_CONFIRM_LIVE='ENABLE LIVE TRADING'")
            print("=" * 64)
            return 2

    interval = float(os.getenv("BOT_TICK_SECONDS", "5"))
    service.start()
    log_event(log, "RUN_BOT", f"loop started in {service.mode.value} mode",
              interval=interval)
    try:
        while True:
            result = service.tick_once()
            if result.signal is not None and result.opened_trade:
                log_event(log, "TRADE_OPENED", "engine opened a trade",
                          signal=result.signal.direction.value)
            time.sleep(interval)
    except KeyboardInterrupt:
        service.stop()
        log_event(log, "RUN_BOT", "loop stopped by user")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
