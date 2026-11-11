import pytest

from mt5_ai.config import Settings


def test_defaults_are_conservative():
    s = Settings()
    assert s.allow_live is False and s.symbols == ("XAUUSD*",)
    assert (s.max_risk_pct, s.max_trades_per_day, s.max_open_positions) == (1.0, 3, 1)


def test_from_env_reads_overrides():
    s = Settings.from_env(
        {"MT5_AI_ALLOW_LIVE": "yes", "MT5_AI_SYMBOLS": "XAUUSD*, EURUSD", "MT5_AI_MAX_RISK_PCT": "0.5",
         "MT5_AI_MAX_TRADES_PER_DAY": "2", "MT5_AI_STATE_DIR": "/tmp/x"}
    )
    assert s.allow_live is True and s.symbols == ("XAUUSD*", "EURUSD")
    assert s.max_risk_pct == 0.5 and s.max_trades_per_day == 2 and str(s.state_dir) == "/tmp/x"


def test_blank_env_values_fall_back_to_defaults():
    s = Settings.from_env({"MT5_AI_MAX_RISK_PCT": "", "MT5_AI_SYMBOLS": " , "})
    assert s.max_risk_pct == 1.0 and s.symbols == ("XAUUSD*",) and s.allow_live is False


@pytest.mark.parametrize("env", [{"MT5_AI_MAX_RISK_PCT": "0"}, {"MT5_AI_MAX_TRADES_PER_DAY": "0"}, {"MT5_AI_MIN_RR": "-1"}])
def test_invalid_values_are_rejected(env):
    with pytest.raises(ValueError):
        Settings.from_env(env)
