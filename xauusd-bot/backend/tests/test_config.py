"""Tests for the configuration system and the LIVE-trading safety gate."""

from __future__ import annotations

import textwrap

import pytest

from app.core.config import BotConfig, Settings, load_config
from app.core.models import TradingMode


def test_load_default_config_from_yaml():
    # The repo ships a config.yaml; loading with no path uses it.
    config = load_config()
    assert config.symbol
    assert config.strategy.ema_slow > config.strategy.ema_fast
    assert 0 <= config.strategy.min_score <= 100


def test_load_missing_config_falls_back_to_defaults(tmp_path):
    config = load_config(tmp_path / "does_not_exist.yaml")
    assert isinstance(config, BotConfig)
    assert config.symbol == "XAUUSD"


def test_ema_slow_must_exceed_fast():
    with pytest.raises(ValueError):
        BotConfig(strategy={"ema_fast": 200, "ema_slow": 50})


def test_candidate_symbols_dedup_primary_first():
    config = BotConfig(symbol="XAUUSD", symbol_aliases=["GOLD", "XAUUSD", "XAUUSDm"])
    assert config.candidate_symbols[0] == "XAUUSD"
    assert config.candidate_symbols == ["XAUUSD", "GOLD", "XAUUSDm"]


def test_custom_yaml_roundtrip(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(
        textwrap.dedent(
            """
            symbol: GOLD
            strategy:
              min_score: 80
              ema_fast: 21
              ema_slow: 55
            risk:
              risk_per_trade: 0.5
            """
        )
    )
    config = load_config(path)
    assert config.symbol == "GOLD"
    assert config.strategy.min_score == 80
    assert config.risk.risk_per_trade == 0.5


def test_live_mode_requires_explicit_gate():
    settings = Settings(trading_mode=TradingMode.LIVE, bot_allow_live=False)
    with pytest.raises(ValueError):
        settings.validated_mode()


def test_live_mode_allowed_when_gated():
    settings = Settings(trading_mode=TradingMode.LIVE, bot_allow_live=True)
    assert settings.validated_mode() == TradingMode.LIVE
    assert settings.requires_real_terminal() is True


def test_paper_is_default_and_uses_mock():
    settings = Settings()
    assert settings.validated_mode() == TradingMode.PAPER
    assert settings.requires_real_terminal() is False
