"""Trading-session filter.

Timezone-aware, no hard-coded local time (spec §14). Presets are expressed in
UTC windows; a broker/user in another timezone configures the preset, not the
code. Used by both the live engine gate and the backtester so results are
consistent.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Dict, Tuple

from app.core.config import TradingSessionsConfig

# (start_hour, end_hour) in UTC. end exclusive. Overnight windows (start > end)
# are handled by wrap-around.
_PRESETS: Dict[str, Tuple[int, int]] = {
    "london": (7, 16),
    "new_york": (12, 21),
    "overlap": (12, 16),      # London/NY overlap
    "all_day": (0, 24),
}


class SessionFilter:
    def __init__(self, config: TradingSessionsConfig) -> None:
        self.config = config
        self._window = _PRESETS.get(config.preset.lower(), (0, 24))

    def is_open(self, dt: datetime) -> bool:
        """True if trading is allowed at ``dt`` (interpreted in UTC)."""
        if not self.config.enabled:
            return True
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        start, end = self._window
        if (start, end) == (0, 24):
            return True
        hour = dt.hour + dt.minute / 60.0
        if start <= end:
            return start <= hour < end
        # Overnight wrap-around (e.g. 22 -> 6).
        return hour >= start or hour < end


__all__ = ["SessionFilter"]
