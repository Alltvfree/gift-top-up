"""AI preset endpoints — fully functional (pure logic, no DB required)."""
from __future__ import annotations

from fastapi import APIRouter

from app.ai.preset_generator import AIPresetGenerator
from app.schemas.ai_preset import (
    PresetGenerateRequest,
    PresetGenerateResponse,
    PresetOut,
)

router = APIRouter()
_generator = AIPresetGenerator()


@router.get("", response_model=list[PresetOut])
async def list_presets() -> list[PresetOut]:
    """List the built-in risk presets and their default parameters."""
    return [
        PresetOut(
            name=name,
            risk_level=config["risk_level"],
            default_parameters={k: v for k, v in config.items() if k != "risk_level"},
        )
        for name, config in AIPresetGenerator.PRESETS.items()
    ]


@router.post("/generate", response_model=PresetGenerateResponse)
async def generate_preset(payload: PresetGenerateRequest) -> PresetGenerateResponse:
    """Generate strategy parameters tuned to balance, symbol and volatility."""
    params = _generator.generate(
        preset=payload.preset.value,
        strategy=payload.strategy.value,
        balance=payload.balance,
        symbol=payload.symbol,
        atr=payload.atr,
    )
    return PresetGenerateResponse(
        preset=payload.preset.value,
        strategy=payload.strategy.value,
        parameters=params,
    )
