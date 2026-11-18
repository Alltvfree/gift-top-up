"""Saves an MT5 account's whole trade history to CSV and prints what it shows, so the lessons
survive a reset. Read-only: it never trades, never changes the account.

    python export_history.py [--days 365] [--out DIR] [--archive]

Run it BEFORE you leave the account (MT5 must be open and logged in to it). It writes:
  deals_<login>_<date>.csv       every deal, as the broker recorded it
  positions_<login>_<date>.csv   one row per position: open/close, lots, hold time, net result
--archive also moves the mt5-ai journal (trades.jsonl, expiries.json) into an archive folder, so a
new account starts with a clean journal. Nothing is deleted. The HALT file is left alone.
"""
from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path

import pandas as pd


def positions_from_deals(deals, m) -> pd.DataFrame:
    """m: the MetaTrader5 module (for the DEAL_* constants)."""
    rows: dict[int, dict] = {}
    outs = (m.DEAL_ENTRY_OUT, m.DEAL_ENTRY_INOUT, m.DEAL_ENTRY_OUT_BY)
    for d in sorted(deals, key=lambda d: d.time):
        if d.type not in (m.DEAL_TYPE_BUY, m.DEAL_TYPE_SELL):
            continue
        r = rows.setdefault(int(d.position_id), {"position": int(d.position_id), "symbol": d.symbol, "side": None, "lots": 0.0,
                            "open_time": None, "close_time": None, "open_price": None, "close_price": None,
                            "net": 0.0, "comment": "", "magic": int(d.magic), "closed": False})
        r["net"] += float(d.profit) + float(d.commission) + float(d.swap) + float(getattr(d, "fee", 0.0))
        if d.entry == m.DEAL_ENTRY_IN:
            r.update(side="BUY" if d.type == m.DEAL_TYPE_BUY else "SELL", lots=float(d.volume),
                     open_time=pd.to_datetime(d.time, unit="s"), open_price=float(d.price), comment=d.comment or "", magic=int(d.magic))
        elif d.entry in outs:
            r.update(close_time=pd.to_datetime(d.time, unit="s"), close_price=float(d.price), closed=True)
    df = pd.DataFrame(rows.values())
    if df.empty:
        return df
    df["hold_seconds"] = (df["close_time"] - df["open_time"]).dt.total_seconds()
    return df.sort_values("open_time").reset_index(drop=True)


def summarize(df: pd.DataFrame, balance_start: float | None = None) -> list[str]:
    c = df[df["closed"]].copy() if not df.empty else df
    if c.empty:
        return ["No closed positions found."]
    n, wins = len(c), int((c["net"] > 0).sum())
    out = [f"{n} closed positions, {wins} winners ({wins / n:.0%}). Net {c['net'].sum():+.2f}.",
           f"Average winner {c.loc[c['net'] > 0, 'net'].mean() if wins else 0:+.2f}, average loser {c.loc[c['net'] <= 0, 'net'].mean() if n - wins else 0:+.2f}."]
    worst = c.nsmallest(3, "net")
    out.append("Worst three: " + "; ".join(f"{r.symbol} {r.side} {r.lots:g} lots {r.net:+.2f}" for r in worst.itertuples()))
    out.append(f"Lot sizes used: smallest {c['lots'].min():g}, median {c['lots'].median():g}, largest {c['lots'].max():g}.")
    mine = c["comment"].str.contains("mt5-ai", na=False)
    if mine.any():
        out.append(f"Placed through the mt5-ai server: {int(mine.sum())} positions, net {c.loc[mine, 'net'].sum():+.2f}. "
                   f"Everything else (manual / other EAs): {int((~mine).sum())} positions, net {c.loc[~mine, 'net'].sum():+.2f}.")
    out.append(f"Median hold: {c['hold_seconds'].median():.0f}s. Positions held under 2 minutes: {int((c['hold_seconds'] < 120).sum())}.")
    # losing streak, and how lot size moved after losses (a classic tilt signature)
    streak = best = 0
    for v in c["net"]:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    out.append(f"Longest losing streak: {best}.")
    after_loss = c["lots"].shift(-1)[c["net"] <= 0].dropna()
    after_win = c["lots"].shift(-1)[c["net"] > 0].dropna()
    if len(after_loss) >= 3 and len(after_win) >= 3:
        out.append(f"Average next lot after a loss {after_loss.mean():g} vs after a win {after_win.mean():g}"
                   + (" - size grew after losses." if after_loss.mean() > 1.3 * after_win.mean() else "."))
    return out


def archive_journal(state_dir: Path, extra_files: list[Path]) -> Path:
    dest = state_dir / "archive" / time.strftime("%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("trades.jsonl", "expiries.json"):
        if (state_dir / name).exists():
            shutil.move(str(state_dir / name), str(dest / name))
    for f in extra_files:
        shutil.copy2(f, dest / f.name)
    return dest


def main() -> None:
    import MetaTrader5 as mt5

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--out", default=str(Path.home() / "Documents" / "mt5-learning"))
    ap.add_argument("--archive", action="store_true")
    a = ap.parse_args()

    if not mt5.initialize():
        raise SystemExit(f"Could not connect to MT5 ({mt5.last_error()}). Open the terminal and log in to the account first.")
    try:
        acct = mt5.account_info()
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        deals = mt5.history_deals_get((now - pd.Timedelta(days=a.days)).to_pydatetime(), (now + pd.Timedelta(days=3)).to_pydatetime()) or ()
    finally:
        mt5.shutdown()
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{acct.login}_{time.strftime('%Y%m%d')}"
    deals_df = pd.DataFrame([d._asdict() for d in deals])
    pos_df = positions_from_deals(deals, mt5)
    f1, f2 = out_dir / f"deals_{tag}.csv", out_dir / f"positions_{tag}.csv"
    deals_df.to_csv(f1, index=False)
    pos_df.to_csv(f2, index=False)
    print(f"Account {acct.login} on {acct.server}: {len(deals_df)} deals, {len(pos_df)} positions.")
    print(f"Saved:\n  {f1}\n  {f2}\n")
    print("What it shows:")
    for line in summarize(pos_df):
        print("  -", line)
    if a.archive:
        dest = archive_journal(Path.home() / ".mt5-ai", [f1, f2])
        print(f"\nJournal archived to {dest} (nothing deleted; HALT file untouched).")


if __name__ == "__main__":
    main()
