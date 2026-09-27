from backtest.config import SignalConfig
from backtest.signal_engine import decide_side


def test_independent_thresholds():
    cfg = SignalConfig(buy_threshold=0.6, sell_threshold=0.6)
    assert decide_side(0.61, 0.10, cfg) == "BUY"
    assert decide_side(0.60, 0.10, cfg) == "BUY"
    assert decide_side(0.10, 0.61, cfg) == "SELL"
    assert decide_side(0.10, 0.60, cfg) == "SELL"
    assert decide_side(0.50, 0.50, cfg) == "NO_TRADE"


def test_sell_is_not_inferred_from_a_low_buy_probability():
    """The exact bug a live BTCUSDm run caught: SELL must require the
    SELL model's OWN probability to clear its OWN threshold, not just a
    low BUY probability."""
    cfg = SignalConfig(buy_threshold=0.6, sell_threshold=0.6)
    assert decide_side(0.05, 0.05, cfg) == "NO_TRADE"  # BUY is very unlikely, but SELL was never confident either


def test_both_sides_confident_is_a_conflict_not_a_tiebreak():
    cfg = SignalConfig(buy_threshold=0.6, sell_threshold=0.6)
    assert decide_side(0.9, 0.9, cfg) == "NO_TRADE"


def test_trade_buy_and_trade_sell_toggles():
    cfg = SignalConfig(buy_threshold=0.6, sell_threshold=0.6, trade_buy=False)
    assert decide_side(0.99, 0.10, cfg) == "NO_TRADE"
    cfg2 = SignalConfig(buy_threshold=0.6, sell_threshold=0.6, trade_sell=False)
    assert decide_side(0.10, 0.99, cfg2) == "NO_TRADE"
