"""Entrypoint — connect, then run one trading-engine iteration.

    cd xauusd-bot/backend
    PYTHONPATH=. python -m app.main

In PAPER/BACKTEST mode this uses the mock adapter (SYNTHETIC data) + a simulated
paper broker, so it runs anywhere. In DEMO/LIVE it connects to a real
MetaTrader 5 terminal and broker.

This runs a SINGLE engine iteration (evaluate → risk gate → execute → manage) as
a smoke check. A continuous scheduled loop is a later phase; the logic here is
identical to one tick of that loop.
"""

from __future__ import annotations

from app.core.config import load_config, load_settings
from app.core.logging import configure_logging, get_logger, log_event
from app.core.models import Timeframe
from app.core.state import StateStore
from app.execution.engine import TradingEngine
from app.execution.factory import create_broker
from app.indicators.indicators import atr, ema, rsi
from app.mt5.factory import create_adapter
from app.mt5.market_data import MarketDataService
from app.risk.governor import RiskGovernor
from app.risk.risk_manager import RiskManager
from app.strategies.factory import create_strategy


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

    # --- Phase 3: build the execution stack and run one engine iteration ------
    state_store = StateStore(f"{settings.log_dir}/../data/bot_state.json")
    state = state_store.load()
    broker = create_broker(
        settings, adapter, info, starting_balance=account.balance
    )
    engine = TradingEngine(
        config=config,
        market=market,
        strategy=create_strategy(config),
        risk_manager=RiskManager(config.risk),
        governor=RiskGovernor(config.risk, state),
        broker=broker,
        state=state,
        state_store=state_store,
    )

    result = engine.process_once()
    if result.signal is not None:
        log_event(
            log, "ITERATION",
            f"{result.signal.direction.value} score={result.signal.score}",
            opened=result.opened_trade, closed=len(result.closed),
            stop_updates=result.stop_updates, gate=result.gate_reason,
            skipped=result.skipped_reason,
        )
    else:
        log_event(log, "ITERATION", "no signal this iteration",
                  skipped=result.skipped_reason, gate=result.gate_reason)

    acct = broker.get_account()
    log_event(log, "PAPER_ACCOUNT",
              f"balance={acct.balance:.2f} equity={acct.equity:.2f}",
              open_positions=len(broker.get_positions(info.name)))

    adapter.disconnect()
    log_event(log, "BOT_SHUTDOWN", "engine iteration complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
