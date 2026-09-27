"""Chart rendering for the HTML report (Phase 16) — plain inline SVG, no
matplotlib.

Deliberately dependency-free: matplotlib has no prebuilt wheel yet for very
new CPython releases (confirmed against PyPI — not even its latest release
ships a cp314 wheel for any platform), and compiling it from source needs a
C compiler that most Windows VPSes simply don't have installed. Three
simple line/area/bar charts don't need a plotting library at all — pure
Python string-building into SVG markup works everywhere the interpreter
itself runs, with zero install step.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_WIDTH, _HEIGHT = 900, 320
_PAD_LEFT, _PAD_RIGHT, _PAD_TOP, _PAD_BOTTOM = 60, 20, 20, 30


def _scale(values: pd.Series, lo: float, hi: float, out_lo: float, out_hi: float) -> list[float]:
    span = hi - lo
    if span == 0:
        return [(out_lo + out_hi) / 2.0] * len(values)
    return [out_lo + (v - lo) / span * (out_hi - out_lo) for v in values]


def _svg_wrapper(title: str, body: str, width: int = _WIDTH, height: int = _HEIGHT) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" height="{height}" font-family="-apple-system,Segoe UI,Arial,sans-serif">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>'
        f'<text x="{width / 2}" y="16" font-size="13" text-anchor="middle" fill="#333">{title}</text>'
        f"{body}</svg>"
    )


def _empty_chart(title: str) -> str:
    return _svg_wrapper(
        title, f'<text x="{_WIDTH / 2}" y="{_HEIGHT / 2}" text-anchor="middle" fill="#999">No data</text>'
    )


def _line_series(xs: list[float], ys: list[float], color: str, label: str) -> str:
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.5"/>'


def _axis_labels(y_lo: float, y_hi: float) -> str:
    top_y, bottom_y = _PAD_TOP + 10, _HEIGHT - _PAD_BOTTOM
    return (
        f'<text x="{_PAD_LEFT - 8}" y="{top_y}" font-size="10" text-anchor="end" fill="#666">{y_hi:,.0f}</text>'
        f'<text x="{_PAD_LEFT - 8}" y="{bottom_y}" font-size="10" text-anchor="end" fill="#666">{y_lo:,.0f}</text>'
    )


def equity_curve_svg(equity_curve: pd.DataFrame) -> str:
    if equity_curve.empty:
        return _empty_chart("Equity Curve")
    lo = min(equity_curve["balance"].min(), equity_curve["equity"].min())
    hi = max(equity_curve["balance"].max(), equity_curve["equity"].max())
    n = len(equity_curve)
    xs = _scale(pd.Series(range(n)), 0, max(n - 1, 1), _PAD_LEFT, _WIDTH - _PAD_RIGHT)
    balance_ys = _scale(equity_curve["balance"], lo, hi, _HEIGHT - _PAD_BOTTOM, _PAD_TOP)
    equity_ys = _scale(equity_curve["equity"], lo, hi, _HEIGHT - _PAD_BOTTOM, _PAD_TOP)
    body = (
        _axis_labels(lo, hi)
        + _line_series(xs, balance_ys, "#1f6feb", "Balance")
        + _line_series(xs, equity_ys, "#57ab5a", "Equity")
        + f'<text x="{_WIDTH - _PAD_RIGHT - 90}" y="{_PAD_TOP}" font-size="10" fill="#1f6feb">— Balance</text>'
        + f'<text x="{_WIDTH - _PAD_RIGHT - 90}" y="{_PAD_TOP + 14}" font-size="10" fill="#57ab5a">— Equity</text>'
    )
    return _svg_wrapper("Equity Curve", body)


def drawdown_svg(equity_curve: pd.DataFrame) -> str:
    if equity_curve.empty:
        return _empty_chart("Drawdown %")
    hi = max(equity_curve["drawdown_percent"].max(), 1e-9)
    n = len(equity_curve)
    xs = _scale(pd.Series(range(n)), 0, max(n - 1, 1), _PAD_LEFT, _WIDTH - _PAD_RIGHT)
    ys = _scale(equity_curve["drawdown_percent"], 0, hi, _HEIGHT - _PAD_BOTTOM, _PAD_TOP)
    baseline = _HEIGHT - _PAD_BOTTOM
    poly_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{_PAD_LEFT:.1f},{baseline:.1f} {poly_points} {_WIDTH - _PAD_RIGHT:.1f},{baseline:.1f}"
    body = _axis_labels(0, hi) + f'<polygon points="{area}" fill="#da3633" opacity="0.5"/>'
    return _svg_wrapper("Drawdown %", body)


def trade_distribution_svg(trades: pd.DataFrame) -> str:
    if trades.empty:
        return _empty_chart("Trade P&L Distribution")
    pnl = trades["net_pnl"]
    bins = min(30, max(5, len(pnl) // 3))
    counts, edges = _histogram(pnl.tolist(), bins)
    max_count = max(counts) or 1
    plot_width = _WIDTH - _PAD_LEFT - _PAD_RIGHT
    bar_width = plot_width / bins
    bars = []
    zero_x = None
    lo, hi = edges[0], edges[-1]
    for i, count in enumerate(counts):
        x = _PAD_LEFT + i * bar_width
        bar_h = (count / max_count) * (_HEIGHT - _PAD_TOP - _PAD_BOTTOM)
        y = _HEIGHT - _PAD_BOTTOM - bar_h
        color = "#57ab5a" if (edges[i] + edges[i + 1]) / 2 >= 0 else "#da3633"
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width * 0.9:.1f}" height="{bar_h:.1f}" fill="{color}"/>')
        if edges[i] <= 0 <= edges[i + 1] and zero_x is None:
            zero_x = x
    zero_line = ""
    if lo < 0 < hi:
        zx = _PAD_LEFT + (0 - lo) / (hi - lo) * plot_width
        zero_line = f'<line x1="{zx:.1f}" y1="{_PAD_TOP}" x2="{zx:.1f}" y2="{_HEIGHT - _PAD_BOTTOM}" stroke="black" stroke-width="1"/>'
    body = "".join(bars) + zero_line
    return _svg_wrapper("Trade P&L Distribution", body)


def _histogram(values: list[float], bins: int) -> tuple[list[int], list[float]]:
    lo, hi = min(values), max(values)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    width = (hi - lo) / bins
    edges = [lo + i * width for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    return counts, edges


def write_charts(equity_curve: pd.DataFrame, trades: pd.DataFrame, out_dir: Path) -> None:
    (out_dir / "equity_curve.svg").write_text(equity_curve_svg(equity_curve))
    (out_dir / "drawdown.svg").write_text(drawdown_svg(equity_curve))
    (out_dir / "trade_distribution.svg").write_text(trade_distribution_svg(trades))
