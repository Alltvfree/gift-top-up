from backtest.config import SignalConfig
from backtest.signal_engine import decide_side


def test_thresholds():
    cfg = SignalConfig(buy_threshold=0.6, sell_threshold=0.4)
    assert decide_side(0.61, cfg) == "BUY"
    assert decide_side(0.60, cfg) == "BUY"
    assert decide_side(0.39, cfg) == "SELL"
    assert decide_side(0.40, cfg) == "SELL"
    assert decide_side(0.5, cfg) == "NO_TRADE"
