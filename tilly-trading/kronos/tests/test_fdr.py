import math

import numpy as np
import pytest

from backtest.compare_setups import compare
from backtest.config import load_config
from backtest.fdr import benjamini_hochberg, normal_two_sided_p
from backtest.symbols import get_symbol_spec
from conftest import make_synthetic_ohlc


def test_normal_p_values():
    assert normal_two_sided_p(0.0) == pytest.approx(1.0)
    assert normal_two_sided_p(1.96) == pytest.approx(0.05, abs=0.001) and normal_two_sided_p(-1.96) == normal_two_sided_p(1.96)
    assert math.isnan(normal_two_sided_p(float("nan"))) and math.isnan(normal_two_sided_p(None))


def test_benjamini_hochberg_matches_the_textbook_example():
    p = [0.01, 0.04, 0.03, 0.005]
    q = benjamini_hochberg(p)
    assert q == pytest.approx([0.02, 0.04, 0.04, 0.02])         # sorted: .005,.01,.03,.04 -> .02,.02,.04,.04
    assert all(qi >= pi for qi, pi in zip(q, p))


def test_nan_is_skipped_and_a_larger_family_makes_everything_harder():
    q = benjamini_hochberg([0.01, float("nan"), 0.04])
    assert math.isnan(q[1]) and q[0] == pytest.approx(0.02) and q[2] == pytest.approx(0.04)
    small, big = benjamini_hochberg([0.01, 0.2]), benjamini_hochberg([0.01, 0.2], family_size=25)
    assert big[0] > small[0] and big[0] == pytest.approx(0.25)


def test_a_lucky_looking_row_does_not_survive_when_many_ideas_were_tried():
    # one p = 0.03 among 25 tried: raw 'significant', but the corrected q is far above 0.05
    assert benjamini_hochberg([0.03], family_size=25)[0] > 0.5


def test_compare_adds_p_q_and_survives_columns_and_no_row_survives_on_random_data():
    cfg, spec = load_config("config/setup_xauusd.toml"), get_symbol_spec("XAUUSDm")
    df = make_synthetic_ohlc(8000, freq="15min", seed=17)
    table = compare(df, None, cfg, spec, min_trades=50, n_null=0, only=["mayfair_rsi", "dtc_ribbon", "smc_sweep"], family_size=25)
    assert {"p_value", "q_value", "survives_fdr"} <= set(table.columns)
    assert not table["survives_fdr"].any()                       # no edge was planted, so none may be called real
