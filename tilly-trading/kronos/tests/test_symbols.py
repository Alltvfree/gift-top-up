from backtest.symbols import get_symbol_spec


def test_known_symbols_have_distinct_specs():
    btc = get_symbol_spec("BTCUSDm")
    xau = get_symbol_spec("XAUUSDm")
    assert btc.contract_size != xau.contract_size or btc.tick_value != xau.tick_value, (
        "BTCUSDm and XAUUSDm must not silently share contract specs — see symbols.py docstring."
    )


def test_round_volume_respects_min_max_step():
    spec = get_symbol_spec("BTCUSDm")
    assert spec.round_volume(0.0) == 0.0
    assert spec.round_volume(0.001) == spec.volume_min
    assert spec.round_volume(1000.0) == spec.volume_max
    rounded = spec.round_volume(0.017)
    steps = rounded / spec.volume_step
    assert abs(steps - round(steps)) < 1e-9, "rounded volume must land on a volume_step multiple"


def test_real_account_symbol_without_suffix_resolves():
    real = get_symbol_spec("XAUUSD")
    demo = get_symbol_spec("XAUUSDm")
    assert real.symbol == "XAUUSD"
    assert (real.contract_size, real.point, real.tick_value) == (demo.contract_size, demo.point, demo.tick_value)
    assert get_symbol_spec("BTCUSD").symbol == "BTCUSD"


def test_unknown_symbol_raises():
    try:
        get_symbol_spec("NOT_A_REAL_SYMBOL")
        assert False, "expected ValueError"
    except ValueError:
        pass
