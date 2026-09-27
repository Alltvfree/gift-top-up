"""Performance metrics (Phase 15) — trade/risk/return metrics kept
deliberately separate from model (classification) metrics. High
classification accuracy is not the same question as profitability; the
report must never conflate the two (see kronos/README.md's "AUC vs
accuracy" discussion — this project has already been burned by treating
them as interchangeable more than once).
"""
from __future__ import annotations

import math

import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def model_metrics(y_true: pd.Series, y_pred_proba: pd.Series, threshold: float = 0.5) -> dict:
    y_true = y_true.dropna()
    y_pred_proba = y_pred_proba.loc[y_true.index]
    if y_true.nunique() < 2:
        auc = float("nan")
    else:
        auc = float(roc_auc_score(y_true, y_pred_proba))
    y_pred = (y_pred_proba >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "auc": auc,
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "prediction_mean": float(y_pred_proba.mean()),
        "prediction_std": float(y_pred_proba.std()),
        "positive_rate": float(y_true.mean()),
    }


def _sharpe(returns: pd.Series, periods_per_year: float) -> float:
    if returns.std(ddof=0) == 0 or len(returns) < 2:
        return 0.0
    return float(returns.mean() / returns.std(ddof=0) * math.sqrt(periods_per_year))


def _sortino(returns: pd.Series, periods_per_year: float) -> float:
    downside = returns[returns < 0]
    if len(downside) == 0 or downside.std(ddof=0) == 0:
        return 0.0
    return float(returns.mean() / downside.std(ddof=0) * math.sqrt(periods_per_year))


def trading_metrics(
    trades: pd.DataFrame, equity_curve: pd.DataFrame, initial_balance: float, bars_per_year: float = 0.0
) -> dict:
    """trades: simulator.trades_to_frame() output (may be empty).
    equity_curve: account.Account.to_frame() output (may be empty).
    bars_per_year: only used for Sharpe/Sortino annualization; pass 0 to
    skip annualizing (leaves the ratio in per-trade units, still valid for
    ranking strategies against each other within the same run)."""
    if trades.empty:
        return {
            "total_trades": 0,
            "note": "No trades were opened in this window — either no signal crossed the "
            "configured thresholds, or every signal was skipped for lack of a valid position size.",
        }

    wins = trades[trades["net_pnl"] > 0]
    losses = trades[trades["net_pnl"] <= 0]
    # "Gross" profit/loss means pre-commission (the trades' own `gross_pnl`
    # column — see simulator.Trade), NOT `net_pnl` again. A trade's win/loss
    # bucket is still decided by its actual (net, commission-included)
    # result — what mattered to the account — but the bucket TOTALS must
    # come from gross_pnl or "gross" vs "net" would report the same number
    # twice and profit_factor would silently be net/net instead of the
    # pre-commission figure Phase 8/15 asks for.
    gross_profit = wins["gross_pnl"].sum()
    gross_loss = losses["gross_pnl"].sum()  # negative or zero
    final_balance = initial_balance + trades["net_pnl"].sum()

    consecutive_wins = _max_consecutive(trades["net_pnl"] > 0)
    consecutive_losses = _max_consecutive(trades["net_pnl"] <= 0)

    per_trade_returns = trades["net_pnl"] / initial_balance
    max_dd = float(equity_curve["drawdown"].max()) if not equity_curve.empty else 0.0
    max_dd_pct = float(equity_curve["drawdown_percent"].max()) if not equity_curve.empty else 0.0

    return {
        # Trade metrics
        "total_trades": int(len(trades)),
        "winning_trades": int(len(wins)),
        "losing_trades": int(len(losses)),
        "win_rate": float(len(wins) / len(trades)),
        "average_win": float(wins["net_pnl"].mean()) if len(wins) else 0.0,
        "average_loss": float(losses["net_pnl"].mean()) if len(losses) else 0.0,
        "largest_win": float(wins["net_pnl"].max()) if len(wins) else 0.0,
        "largest_loss": float(losses["net_pnl"].min()) if len(losses) else 0.0,
        "average_trade": float(trades["net_pnl"].mean()),
        "expectancy": float(trades["net_pnl"].mean()),
        "profit_factor": float(gross_profit / abs(gross_loss)) if gross_loss != 0 else float("inf"),
        "payoff_ratio": (
            float(abs(wins["net_pnl"].mean() / losses["net_pnl"].mean()))
            if len(wins) and len(losses) and losses["net_pnl"].mean() != 0
            else float("nan")
        ),
        # Risk metrics
        "max_drawdown": max_dd,
        "max_drawdown_percent": max_dd_pct,
        "average_drawdown": float(equity_curve["drawdown"].mean()) if not equity_curve.empty else 0.0,
        "recovery_factor": float(trades["net_pnl"].sum() / max_dd) if max_dd > 0 else float("nan"),
        "sharpe_ratio": _sharpe(per_trade_returns, bars_per_year or len(trades)),
        "sortino_ratio": _sortino(per_trade_returns, bars_per_year or len(trades)),
        "calmar_ratio": (
            float((final_balance / initial_balance - 1) / (max_dd_pct / 100.0))
            if max_dd_pct > 0
            else float("nan")
        ),
        # Return metrics
        "initial_balance": float(initial_balance),
        "final_balance": float(final_balance),
        "net_profit": float(trades["net_pnl"].sum()),
        "net_profit_percent": float((final_balance / initial_balance - 1) * 100.0),
        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "total_commission": float(trades["commission"].sum()),
        "total_spread_cost": float(trades["spread_cost"].sum()),
        "total_slippage_cost": float(trades["slippage_cost"].sum()),
        # Trade behavior
        "average_holding_time": str(trades["holding_time"].mean()),
        "median_holding_time": str(trades["holding_time"].median()),
        "long_trades": int((trades["direction"] == "BUY").sum()),
        "short_trades": int((trades["direction"] == "SELL").sum()),
        "buy_win_rate": _win_rate_for(trades, "BUY"),
        "sell_win_rate": _win_rate_for(trades, "SELL"),
        "tp_exits": int((trades["exit_reason"] == "TP").sum()),
        "sl_exits": int((trades["exit_reason"] == "SL").sum()),
        "time_exits": int((trades["exit_reason"] == "TIME_EXIT").sum()),
        "end_of_test_exits": int((trades["exit_reason"] == "END_OF_TEST").sum()),
        "consecutive_wins": consecutive_wins,
        "consecutive_losses": consecutive_losses,
    }


def _win_rate_for(trades: pd.DataFrame, direction: str) -> float:
    subset = trades[trades["direction"] == direction]
    if subset.empty:
        return float("nan")
    return float((subset["net_pnl"] > 0).mean())


def _max_consecutive(mask: pd.Series) -> int:
    best = current = 0
    for value in mask:
        current = current + 1 if value else 0
        best = max(best, current)
    return best
