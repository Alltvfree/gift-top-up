"""Configuration system.

Two layers, kept strictly separate:

* **Secrets & runtime environment** (credentials, DB URL, trading mode) come from
  environment variables / ``.env`` via :class:`Settings`. These are NEVER stored
  in the YAML file or committed to git.
* **Strategy & risk parameters** come from a YAML config file, validated into the
  typed :class:`BotConfig` model.

Nothing in this module hard-codes a credential.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.models import TradingMode

# --- Paths -------------------------------------------------------------------
# .../backend/app/core/config.py -> project root is three parents up from `app`.
APP_DIR = Path(__file__).resolve().parent.parent          # .../backend/app
BACKEND_DIR = APP_DIR.parent                              # .../backend
PROJECT_ROOT = BACKEND_DIR.parent                        # .../xauusd-bot
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


# =============================================================================
# Secrets / environment (never serialized to YAML)
# =============================================================================
class Settings(BaseSettings):
    """Environment-driven settings. Reads ``.env`` if present."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    trading_mode: TradingMode = TradingMode.PAPER

    mt5_login: Optional[int] = None
    mt5_password: Optional[str] = None
    mt5_server: Optional[str] = None
    mt5_terminal_path: Optional[str] = None

    # Explicit live-trading gate. LIVE mode is rejected unless this is true.
    bot_allow_live: bool = False

    database_url: str = "sqlite:///./data/bot.db"

    log_level: str = "INFO"
    log_dir: str = "./logs"

    def validated_mode(self) -> TradingMode:
        """Return the trading mode, enforcing the live-trading safety gate.

        LIVE mode requires ``BOT_ALLOW_LIVE=true``; otherwise we refuse to run
        rather than silently downgrading, so the operator's intent is never
        ambiguous.
        """
        if self.trading_mode == TradingMode.LIVE and not self.bot_allow_live:
            raise ValueError(
                "TRADING_MODE=LIVE requires BOT_ALLOW_LIVE=true in the "
                "environment. Refusing to start in LIVE mode without it."
            )
        return self.trading_mode

    def requires_real_terminal(self) -> bool:
        """DEMO and LIVE talk to a real MT5 terminal; the rest use the mock."""
        return self.trading_mode in (TradingMode.DEMO, TradingMode.LIVE)


# =============================================================================
# Strategy / risk configuration (from YAML)
# =============================================================================
class TimeframesConfig(BaseModel):
    trend: str = "H1"
    setup: str = "M15"
    entry: str = "M5"


class StrategyConfig(BaseModel):
    name: str = "XAUUSD_TrendPullback_v1"
    version: str = "1.0.0"
    min_score: int = Field(75, ge=0, le=100)
    ema_fast: int = Field(50, gt=0)
    ema_slow: int = Field(200, gt=0)
    ema_short: int = Field(20, gt=0)
    rsi_period: int = Field(14, gt=0)
    rsi_buy_threshold: float = 50.0
    rsi_sell_threshold: float = 50.0
    atr_period: int = Field(14, gt=0)

    @field_validator("ema_slow")
    @classmethod
    def _slow_gt_fast(cls, v: int, info):
        fast = info.data.get("ema_fast")
        if fast is not None and v <= fast:
            raise ValueError("ema_slow must be greater than ema_fast")
        return v


class RiskConfig(BaseModel):
    risk_per_trade: float = Field(1.0, gt=0, le=100)
    max_daily_loss: float = Field(3.0, gt=0, le=100)
    max_drawdown: float = Field(10.0, gt=0, le=100)
    max_daily_trades: int = Field(5, ge=1)
    max_positions: int = Field(1, ge=1)
    max_spread_points: float = Field(50.0, gt=0)
    cooldown_minutes: int = Field(15, ge=0)


class StopLossConfig(BaseModel):
    atr_period: int = Field(14, gt=0)
    atr_multiplier: float = Field(1.5, gt=0)


class TakeProfitConfig(BaseModel):
    risk_reward: float = Field(2.0, gt=0)


class BreakEvenConfig(BaseModel):
    enabled: bool = True
    trigger_r: float = Field(1.0, gt=0)
    buffer_points: float = Field(5.0, ge=0)


class TrailingStopConfig(BaseModel):
    enabled: bool = True
    atr_multiplier: float = Field(1.5, gt=0)


class TradingSessionsConfig(BaseModel):
    enabled: bool = True
    timezone: str = "UTC"
    preset: str = "overlap"


class NewsFilterConfig(BaseModel):
    enabled: bool = False
    minutes_before: int = Field(30, ge=0)
    minutes_after: int = Field(30, ge=0)


class ModeConfig(BaseModel):
    default: str = "PAPER"


class BotConfig(BaseModel):
    """Fully-validated bot configuration loaded from YAML."""

    symbol: str = "XAUUSD"
    symbol_aliases: List[str] = Field(
        default_factory=lambda: ["XAUUSD", "XAUUSDm", "XAUUSD.a", "GOLD"]
    )
    timeframes: TimeframesConfig = Field(default_factory=TimeframesConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    stop_loss: StopLossConfig = Field(default_factory=StopLossConfig)
    take_profit: TakeProfitConfig = Field(default_factory=TakeProfitConfig)
    break_even: BreakEvenConfig = Field(default_factory=BreakEvenConfig)
    trailing_stop: TrailingStopConfig = Field(default_factory=TrailingStopConfig)
    trading_sessions: TradingSessionsConfig = Field(
        default_factory=TradingSessionsConfig
    )
    news_filter: NewsFilterConfig = Field(default_factory=NewsFilterConfig)
    mode: ModeConfig = Field(default_factory=ModeConfig)

    @property
    def candidate_symbols(self) -> List[str]:
        """Symbol plus aliases, de-duplicated, primary first."""
        seen: List[str] = []
        for name in [self.symbol, *self.symbol_aliases]:
            if name and name not in seen:
                seen.append(name)
        return seen


def load_config(path: Optional[str | Path] = None) -> BotConfig:
    """Load and validate the YAML config.

    Missing file falls back to model defaults so the bot can still start (and
    tests can run) without a config file present.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return BotConfig()
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return BotConfig(**raw)


def load_settings() -> Settings:
    """Load environment-driven settings (secrets, mode)."""
    return Settings()


__all__ = [
    "Settings",
    "BotConfig",
    "load_config",
    "load_settings",
    "PROJECT_ROOT",
    "DEFAULT_CONFIG_PATH",
]
