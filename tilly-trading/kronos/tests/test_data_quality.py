import pandas as pd

from backtest.data_quality import validate_ohlc


def _base_df():
    times = pd.date_range("2024-01-01", periods=10, freq="5min", tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.5] * 10,
            "tick_volume": [50] * 10,
            "spread": [20] * 10,
        }
    )


def test_clean_data_passes_through_untouched():
    df = _base_df()
    cleaned, report = validate_ohlc(df, "TEST", "M5")
    assert report.is_clean
    assert report.rows_discarded == 0
    assert len(cleaned) == len(df)


def test_duplicate_timestamp_is_discarded_and_logged():
    df = _base_df()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)  # duplicate the first row's timestamp
    cleaned, report = validate_ohlc(df, "TEST", "M5")
    assert report.duplicate_timestamps == 1
    assert report.rows_discarded == 1
    assert len(cleaned) == 10
    assert any("duplicate" in n.lower() for n in report.notes)


def test_out_of_order_is_resorted_not_discarded():
    df = _base_df()
    df = df.iloc[[1, 0, 2, 3, 4, 5, 6, 7, 8, 9]].reset_index(drop=True)
    cleaned, report = validate_ohlc(df, "TEST", "M5")
    assert report.out_of_order > 0
    assert cleaned["time"].is_monotonic_increasing
    assert len(cleaned) == 10  # nothing discarded, just re-sorted


def test_invalid_ohlc_ordering_is_discarded():
    df = _base_df()
    df.loc[3, "high"] = 50.0  # high below low/open/close — structurally impossible
    cleaned, report = validate_ohlc(df, "TEST", "M5")
    assert report.invalid_ohlc == 1
    assert report.rows_discarded == 1
    assert 3 not in cleaned.index or len(cleaned) == 9


def test_nonpositive_price_is_discarded():
    df = _base_df()
    df.loc[5, "close"] = -1.0
    df.loc[5, "low"] = -2.0
    cleaned, report = validate_ohlc(df, "TEST", "M5")
    assert report.zero_or_negative_price == 1
    assert len(cleaned) == 9


def test_extreme_gap_reported_not_discarded():
    df = _base_df()
    df.loc[5:, "time"] = df.loc[5:, "time"] + pd.Timedelta(hours=5)  # huge gap after row 4
    cleaned, report = validate_ohlc(df, "TEST", "M5", expected_gap=pd.Timedelta(minutes=5))
    assert report.extreme_gaps >= 1
    assert len(cleaned) == 10  # a gap is real history, never discarded
