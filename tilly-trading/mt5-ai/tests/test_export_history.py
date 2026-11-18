import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from export_history import archive_journal, positions_from_deals, summarize
from fake_mt5 import FakeMT5

m = FakeMT5()


def deal(pid, entry, t, profit=0.0, vol=0.1, typ=0, price=100.0, comment="", magic=0, commission=0.0):
    return NS(position_id=pid, entry=entry, time=t, profit=profit, volume=vol, type=typ, price=price, comment=comment,
              magic=magic, commission=commission, swap=0.0, fee=0.0, symbol="XAUUSDm")


def test_positions_group_open_and_close_deals_and_net_includes_costs():
    deals = [deal(1, m.DEAL_ENTRY_IN, 1000, typ=m.DEAL_TYPE_BUY, comment="mt5-ai", commission=-0.5),
             deal(1, m.DEAL_ENTRY_OUT, 1090, profit=7.0, typ=m.DEAL_TYPE_SELL, price=101.0, commission=-0.5),
             deal(2, m.DEAL_ENTRY_IN, 2000, typ=m.DEAL_TYPE_SELL, vol=2.0)]
    df = positions_from_deals(deals, m)
    a, b = df.iloc[0], df.iloc[1]
    assert a["side"] == "BUY" and a["closed"] and a["net"] == 6.0 and a["hold_seconds"] == 90
    assert b["side"] == "SELL" and not b["closed"] and b["lots"] == 2.0


def test_balance_deals_are_ignored():
    df = positions_from_deals([deal(0, m.DEAL_ENTRY_IN, 5, typ=m.DEAL_TYPE_BALANCE, profit=1000.0)], m)
    assert df.empty


def test_summary_separates_server_trades_from_manual_and_flags_size_after_losses():
    deals = []
    for i in range(1, 9):
        loss = i % 2 == 1
        deals += [deal(i, m.DEAL_ENTRY_IN, i * 1000, typ=m.DEAL_TYPE_BUY, vol=0.1 if i == 1 else (1.0 if not loss else 0.1),
                       comment="mt5-ai" if i <= 2 else "", magic=26110001 if i <= 2 else 0),
                  deal(i, m.DEAL_ENTRY_OUT, i * 1000 + 60, profit=-10.0 if loss else 5.0, typ=m.DEAL_TYPE_SELL)]
    lines = summarize(positions_from_deals(deals, m))
    text = "\n".join(lines)
    assert "8 closed positions" in text and "Placed through the mt5-ai server: 2 positions" in text
    assert "Longest losing streak" in text and "Positions held under 2 minutes: 8" in text


def test_summary_handles_nothing():
    assert summarize(pd.DataFrame()) == ["No closed positions found."]


def test_archive_moves_the_journal_and_deletes_nothing(tmp_path):
    (tmp_path / "trades.jsonl").write_text("x")
    (tmp_path / "expiries.json").write_text("{}")
    (tmp_path / "HALT").write_text("halted")
    export = tmp_path / "e.csv"
    export.write_text("a")
    dest = archive_journal(tmp_path, [export])
    assert not (tmp_path / "trades.jsonl").exists() and (dest / "trades.jsonl").read_text() == "x"
    assert (dest / "expiries.json").exists() and (dest / "e.csv").exists()
    assert (tmp_path / "HALT").exists()
