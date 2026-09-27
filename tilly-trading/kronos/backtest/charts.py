"""Chart rendering for the HTML report (Phase 16). Isolated in its own
module so matplotlib (a report-only dependency) never has to be imported
by anything on the training/inference hot path.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — no GUI backend on a VPS or CI runner
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def equity_curve_chart(equity_curve: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4))
    if not equity_curve.empty:
        ax.plot(equity_curve["time"], equity_curve["balance"], label="Balance", linewidth=1)
        ax.plot(equity_curve["time"], equity_curve["equity"], label="Equity", linewidth=1, alpha=0.7)
    ax.set_title("Equity Curve")
    ax.set_ylabel("Account currency")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def drawdown_chart(equity_curve: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 3))
    if not equity_curve.empty:
        ax.fill_between(equity_curve["time"], -equity_curve["drawdown_percent"], 0, color="crimson", alpha=0.6)
    ax.set_title("Drawdown %")
    ax.set_ylabel("% of peak equity")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def trade_distribution_chart(trades: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    if not trades.empty:
        ax.hist(trades["net_pnl"], bins=min(30, max(5, len(trades) // 3)), color="steelblue")
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title("Trade P&L Distribution")
    ax.set_xlabel("Net P&L")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
