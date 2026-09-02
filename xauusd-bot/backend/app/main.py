"""Phase 1 entrypoint — foundation smoke check.

Run as a module to verify the foundation wires together end-to-end:

    cd xauusd-bot
    python -m app.main            # from the backend/ dir, or:
    PYTHONPATH=backend python -m app.main

In PAPER/BACKTEST mode this connects to the mock adapter (SYNTHETIC data) so it
runs anywhere. In DEMO/LIVE it connects to a real MetaTrader 5 terminal.

This is NOT the trading loop — the strategy/execution engine arrives in later
phases. It only proves connection, symbol detection, market data and indicators.
"""

from __future__ import annotations

from app.core.config import load_config, load_settings
from app.core.logging import configure_logging, get_logger, log_event
from app.core.models import Timeframe
from app.indicators.indicators import atr, ema, rsi
from app.mt5.factory import create_adapter
from app.mt5.market_data import MarketDataService


def run() -> int:
    settings = load_settings()
    configure_logging(level=settings.log_level, log_dir=settings.log_dir)
    log = get_logger("app.main")

    config = load_config()
    mode = settings.validated_mode()
    log_event(
        log,
        "BOT_STARTUP",
        f"XAUUSD bot foundation starting in {mode.value} mode",
        mode=mode.value,
        symbol=config.symbol,
        strategy=config.strategy.name,
    )

    adapter = create_adapter(settings)
    status = adapter.connect()
    if not status.connected:
        log_event(log, "MT5_CONNECT_FAILED", status.message, level=40)
        return 1
    log_event(log, "MT5_CONNECTED", status.message)

    account = adapter.get_account_info()
    log_event(
        log,
        "ACCOUNT_INFO",
        f"balance={account.balance:.2f} equity={account.equity:.2f}",
        currency=account.currency,
        server=account.server,
    )

    market = MarketDataService(adapter)
    info = market.resolve_symbol(config.candidate_symbols)

    tick = market.get_tick()
    if tick is not None:
        log_event(
            log,
            "TICK",
            f"bid={tick.bid} ask={tick.ask}",
            spread_points=round(tick.spread_points(info), 1),
        )

    # Indicator smoke check on the trend timeframe.
    frame = market.get_ohlc_frame(Timeframe(config.timeframes.trend), 300)
    if not frame.empty:
        close = frame["close"]
        ema_fast = ema(close, config.strategy.ema_fast).iloc[-1]
        ema_slow = ema(close, config.strategy.ema_slow).iloc[-1]
        rsi_val = rsi(close, config.strategy.rsi_period).iloc[-1]
        atr_val = atr(
            frame["high"], frame["low"], close, config.stop_loss.atr_period
        ).iloc[-1]
        log_event(
            log,
            "INDICATORS",
            "latest indicator snapshot",
            timeframe=config.timeframes.trend,
            ema_fast=round(float(ema_fast), info.digits),
            ema_slow=round(float(ema_slow), info.digits),
            rsi=round(float(rsi_val), 2),
            atr=round(float(atr_val), info.digits),
        )

    adapter.disconnect()
    log_event(log, "BOT_SHUTDOWN", "foundation smoke check complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
