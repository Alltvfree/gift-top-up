"""A trade journal built from what this server already logs (trades.jsonl) plus the
broker's own deal history: what you planned, what was placed, how it ended, in R.

R = net result (profit + commission + swap + fees) / the money risked at the stop.
It exists to show, with honest uncertainty, what is and isn't working for YOU,
by tag (setup, session, ...). It does not trade, and it refuses to draw conclusions
from a handful of trades.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

MIN_TRADES_FOR_CONCLUSION = 30


def read_events(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # a torn line must not hide the rest of the journal
    return out


def placed_trades(events: list[dict]) -> list[dict]:
    """One row per order that was actually placed, joined to its plan."""
    plans = {e["ticket"]: e for e in events if e.get("event") == "prepared" and "ticket" in e}
    rows = []
    for e in events:
        if e.get("event") != "placed" or "ticket" not in e:
            continue
        plan = plans.get(e["ticket"], {})
        rows.append({
            "ticket": e["ticket"], "position": e.get("order") or e.get("position"), "placed_at": e.get("ts"),
            "symbol": plan.get("symbol"), "side": plan.get("side"), "lots": plan.get("lots"),
            "sl": plan.get("sl"), "tp": plan.get("tp"), "note": plan.get("note", ""),
            "tags": [t.strip() for t in str(e.get("tags") or plan.get("tags") or "").split(",") if t.strip()],
            "risk_money": e.get("risk_money") or plan.get("risk_money"),
        })
    return rows


def bootstrap_ci(values: np.ndarray, n_boot: int = 4000, seed: int = 7) -> tuple[float, float]:
    if len(values) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = values[rng.integers(0, len(values), size=(n_boot, len(values)))].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _stats(r: list[float]) -> dict:
    a = np.asarray(r, float)
    n = len(a)
    if n == 0:
        return {"trades": 0}
    lo, hi = bootstrap_ci(a)
    out = {"trades": n, "win_rate": round(float((a > 0).mean()), 3), "mean_r": round(float(a.mean()), 3),
           "total_r": round(float(a.sum()), 2), "mean_r_ci95": [round(lo, 3), round(hi, 3)] if n > 1 else None}
    out["reading"] = (f"Only {n} closed trade(s): too few to conclude anything (need {MIN_TRADES_FOR_CONCLUSION}+)."
                      if n < MIN_TRADES_FOR_CONCLUSION else
                      "Above zero with confidence." if lo > 0 else
                      "Below zero with confidence." if hi < 0 else
                      "Indistinguishable from luck at this sample size.")
    return out


def review(trades: list[dict], outcomes: dict) -> dict:
    """trades: placed_trades(); outcomes: {position_id: {"net": float, "closed": bool}}."""
    closed, open_, unknown = [], 0, 0
    for t in trades:
        o = outcomes.get(t["position"])
        if o is None:
            unknown += 1
        elif not o["closed"]:
            open_ += 1
        elif t.get("risk_money"):
            closed.append({**t, "net": o["net"], "r": o["net"] / float(t["risk_money"])})
        else:
            unknown += 1
    by_tag: dict[str, list[float]] = {}
    for t in closed:
        for tag in t["tags"] or ["(untagged)"]:
            by_tag.setdefault(tag, []).append(t["r"])
    return {
        "placed": len(trades), "closed": len(closed), "still_open": open_, "no_outcome_found": unknown,
        "overall": _stats([t["r"] for t in closed]),
        "by_tag": {k: _stats(v) for k, v in sorted(by_tag.items())},
        "recent": [{"ticket": t["ticket"], "symbol": t["symbol"], "side": t["side"], "tags": t["tags"],
                    "net": round(t["net"], 2), "r": round(t["r"], 2), "note": t["note"]} for t in closed[-10:]],
        "caveat": ("Each tag's numbers are separate small samples: with many tags, one will look good by chance. "
                   "Treat a tag as promising only after it holds up on trades logged AFTER you first noticed it."),
    }
