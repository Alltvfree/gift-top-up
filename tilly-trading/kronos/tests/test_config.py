"""backtest/config.py's TOML loading — including a direct check against the
actual shipped config/*.toml files, so a syntax mistake in those (exactly
the kind of thing that broke twice already on the real VPS) fails a test
run instead of only showing up live."""
from pathlib import Path

from backtest.config import config_to_dict, load_config

KRONOS_DIR = Path(__file__).resolve().parent.parent


def test_load_config_with_no_path_returns_pure_defaults():
    cfg = load_config(None)
    assert cfg.symbol == "BTCUSDm"
    assert cfg.walk_forward.train_days == 90
    assert cfg.signal.buy_threshold == 0.60


def test_shipped_backtest_toml_loads_and_matches_documented_values():
    cfg = load_config(KRONOS_DIR / "config" / "backtest.toml")
    assert cfg.symbol == "BTCUSDm"
    assert cfg.higher_timeframe == "H1"
    assert cfg.stop_loss.value == 20000
    assert cfg.take_profit.value == 30000
    assert cfg.spread.mode == "historical"
    assert cfg.execution.next_bar is True
    assert cfg.execution.same_bar_exit_policy == "conservative"


def test_shipped_backtest_xauusd_toml_loads_and_matches_documented_values():
    cfg = load_config(KRONOS_DIR / "config" / "backtest_xauusd.toml")
    assert cfg.symbol == "XAUUSDm"
    assert cfg.stop_loss.value == 200
    assert cfg.take_profit.value == 300


def test_partial_config_falls_back_to_defaults_for_missing_fields(tmp_path):
    partial = tmp_path / "partial.toml"
    partial.write_text('symbol = "XAUUSDm"\n\n[risk]\nrisk_percent = 2.5\n')
    cfg = load_config(partial)
    assert cfg.symbol == "XAUUSDm"  # overridden
    assert cfg.risk.risk_percent == 2.5  # overridden
    assert cfg.risk.mode == "percent_equity"  # default, since risk.mode wasn't in the file
    assert cfg.timeframe == "M5"  # default, since symbol was the only top-level override


def test_config_to_dict_round_trips_every_section():
    cfg = load_config(KRONOS_DIR / "config" / "backtest.toml")
    d = config_to_dict(cfg)
    assert d["symbol"] == "BTCUSDm"
    assert d["walk_forward"]["train_days"] == 90
    assert d["risk"]["mode"] == "percent_equity"
