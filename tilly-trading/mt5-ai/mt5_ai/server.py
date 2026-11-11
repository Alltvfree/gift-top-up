"""MCP server entry point: `python -m mt5_ai` (stdio).

Tools are annotated so Claude clients can treat them correctly: read-only
tools are safe to auto-approve; place_prepared_trade, move_stop and
close_position are marked destructive and should be left on "Needs approval".
"""
from __future__ import annotations

import os
from functools import partial

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .service import Mt5Service

INSTRUCTIONS = """\
MetaTrader 5 trading assistant. Rules that never bend:
- Orders only happen through prepare_trade -> the person says an explicit yes for that exact ticket -> place_prepared_trade. Never skip a step, never place on an implied yes, never reuse a yes for another ticket.
- A BLOCK from prepare_trade is final: report every reason, do not re-word the parameters to sneak past a rule.
- Demo accounts only unless the person has switched real trading on themselves; you cannot.
- If anything looks wrong, or the person says stop, call halt_trading first and explain after.
- Every trade needs a stop-loss and a take-profit. Never widen a stop. Never average down.
- Kronos forecasts and the rule-based setup are unverified signals, not predictions of fact. Say so, and say when they disagree.
"""

_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_COMPUTE = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_PREPARE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
_ORDER = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True)


def build_server(service: Mt5Service) -> FastMCP:
    mcp = FastMCP("mt5", instructions=INSTRUCTIONS)

    async def run(fn, *args, **kwargs):
        # MetaTrader5 / torch calls block; keep the event loop free.
        return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))

    @mcp.tool(annotations=_READ)
    async def account_overview() -> dict:
        """Account mode (DEMO/REAL), balance, equity, free margin, and the risk limits this server enforces. Call this first."""
        return await run(service.account_overview)

    @mcp.tool(annotations=_READ)
    async def symbol_details(symbol: str) -> dict:
        """Contract specification, live bid/ask, spread and broker server time for a symbol (e.g. XAUUSD, or XAUUSDm on a mini account)."""
        return await run(service.symbol_details, symbol)

    @mcp.tool(annotations=_READ)
    async def get_quote(symbol: str) -> dict:
        """Latest bid, ask and spread."""
        return await run(service.get_quote, symbol)

    @mcp.tool(annotations=_READ)
    async def get_candles(symbol: str, timeframe: str = "M15", count: int = 100) -> dict:
        """Recent CLOSED candles (never the still-forming one). timeframe: M1 M5 M15 M30 H1 H4 D1. count up to 1000."""
        return await run(service.get_candles, symbol, timeframe, count)

    @mcp.tool(annotations=_READ)
    async def list_positions() -> dict:
        """Open positions, flagged by whether this server opened them."""
        return await run(service.list_positions)

    @mcp.tool(annotations=_READ)
    async def list_pending_orders() -> dict:
        """Pending (not yet filled) orders on the account."""
        return await run(service.list_pending_orders)

    @mcp.tool(annotations=_READ)
    async def todays_summary(symbol: str | None = None) -> dict:
        """Today's realized P&L across every strategy on the account, trades used, and how much loss budget is left."""
        return await run(service.todays_summary, symbol)

    @mcp.tool(annotations=_COMPUTE)
    async def kronos_forecast(symbol: str, timeframe: str = "M15", lookback: int = 400, horizon_bars: int = 16, samples: int = 5) -> dict:
        """Forecast the next `horizon_bars` candles with the Kronos foundation model on live closed candles. Runs `samples` independent sampled paths and reports the share ending higher. Takes roughly 5 seconds per sample on CPU. An unverified signal, not a prediction."""
        return await run(service.kronos_forecast, symbol, timeframe, lookback, horizon_bars, samples)

    @mcp.tool(annotations=_COMPUTE)
    async def rule_setup_status(symbol: str, timeframe: str = "M15", higher_timeframe: str = "H1") -> dict:
        """Whether the rule-based trend+pullback setup (H1 trend, M15 pullback to EMA20, confirmation candle) fired on the last closed bar, with its structural stop and 2R target."""
        return await run(service.rule_setup_status, symbol, timeframe, higher_timeframe)

    @mcp.tool(annotations=_COMPUTE)
    async def simulate_trade_plan(symbol: str, side: str, sl: float, tp: float, timeframe: str = "M15", horizon_bars: int = 32, simulations: int = 5000, history_bars: int = 2000) -> dict:
        """Replay a trade plan thousands of times from the symbol's own recent candles (direction-neutral): how often target vs stop vs neither, with spread costs. Shows plan geometry, not direction."""
        return await run(service.simulate_trade_plan, symbol, side, sl, tp, timeframe, horizon_bars, simulations, history_bars)

    @mcp.tool(annotations=_PREPARE)
    async def prepare_trade(symbol: str, side: str, sl: float, tp: float, risk_pct: float | None = None, note: str = "") -> dict:
        """Size a trade from the stop distance, run every risk rule and the broker pre-flight, and return PASS with a single-use ticket or BLOCK with every reason. Sends NO order. side is BUY or SELL; sl and tp are absolute prices; risk_pct defaults to the configured maximum."""
        return await run(service.prepare_trade, symbol, side, sl, tp, risk_pct, note)

    @mcp.tool(annotations=_ORDER)
    async def place_prepared_trade(ticket_id: str) -> dict:
        """Send the order for a PASS ticket to MetaTrader 5, after re-checking fresh prices and limits. Call ONLY after the person has replied with an explicit yes for this exact ticket."""
        return await run(service.place_prepared_trade, ticket_id)

    @mcp.tool(annotations=_PREPARE)
    async def halt_trading(reason: str = "") -> dict:
        """Kill switch: block all new entries immediately. Use whenever something looks wrong or the person says stop. Only the person can resume (by deleting the HALT file); open positions keep their broker-side stop and target."""
        return await run(service.halt_trading, reason)

    @mcp.tool(annotations=_ORDER)
    async def move_stop(position_ticket: int, new_sl: float, new_tp: float | None = None) -> dict:
        """Tighten the stop on a position this server opened. Refuses to widen it."""
        return await run(service.move_stop, position_ticket, new_sl, new_tp)

    @mcp.tool(annotations=_ORDER)
    async def close_position(position_ticket: int) -> dict:
        """Close one position this server opened, at market."""
        return await run(service.close_position, position_ticket)

    return mcp


def main() -> None:
    from .broker import Mt5Broker
    from .config import Settings

    settings = Settings.from_env()
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise SystemExit("The MetaTrader5 package is Windows-only: run this on the PC with the terminal. pip install MetaTrader5") from exc

    broker = Mt5Broker(mt5)
    broker.initialize(os.environ.get("MT5_AI_TERMINAL_PATH") or None)

    forecaster = setup = None
    if settings.kronos_repo:
        from .forecast import KronosForecaster

        forecaster = KronosForecaster(settings.kronos_repo, settings.kronos_model)
    if settings.kronos_dir:
        from .setup_adapter import TrendPullbackAdapter

        setup = TrendPullbackAdapter(settings.kronos_dir)

    build_server(Mt5Service(broker, settings, forecaster=forecaster, setup=setup)).run()


if __name__ == "__main__":
    main()
