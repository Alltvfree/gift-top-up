"""Timestamp-safe attachment of news-derived features onto candle rows.

Genuinely TIME-windowed, not row-count-windowed: a reference ChatGPT-
authored implementation (kronos_lgbm_news_ai/news/features.py, reviewed
alongside this one) resampled articles to a 1-minute grid and then called
`.rolling(window=w)` directly on that reindexed-to-candles series — but
`.rolling(window=15)` on a plain integer index means 15 ROWS, not 15
minutes, once the series has been reindexed onto candle timestamps. On M5
candles that silently becomes a 75-minute window; on H1 candles a 15-hour
one. This module instead looks up, for each candle time T, the actual
count/mean sentiment of articles published in (T - window, T] via two
`merge_asof` lookups against each article's cumulative count/sentiment —
correct regardless of candle spacing, and still fully vectorized (no
per-candle Python loop).

Causal by construction: only articles with timestamp <= T ever contribute
to candle T's features (merge_asof direction="backward"), so this can
never see a future article — the one thing to get right here, the same way
merge_higher_timeframe's own docstring explains for higher-timeframe bars.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .sentiment import score_text

DEFAULT_WINDOWS_MINUTES = (15, 60, 240)


def attach_news_features(
    candles: pd.DataFrame, articles: pd.DataFrame, windows_minutes: tuple[int, ...] = DEFAULT_WINDOWS_MINUTES
) -> pd.DataFrame:
    """candles: must have a `time` column (tz-aware UTC, ascending — same
    shape as mt5_data.download_history's output). articles: must have
    `timestamp` (tz-aware UTC), `title`, `description` columns (see
    news/store.py's load_articles). Adds, per window w in windows_minutes:
      - news_count_{w}m: how many articles fell in (T-w, T]
      - news_sentiment_{w}m: their mean sentiment score, 0.0 if none
      - news_sentiment_abs_{w}m: abs of the above — "how much news noise",
        independent of direction
    """
    out = candles.copy()
    if articles.empty:
        for w in windows_minutes:
            out[f"news_count_{w}m"] = 0
            out[f"news_sentiment_{w}m"] = 0.0
            out[f"news_sentiment_abs_{w}m"] = 0.0
        return out

    a = articles.sort_values("timestamp").reset_index(drop=True).copy()
    a["sentiment"] = [score_text(f"{t} {d}") for t, d in zip(a["title"], a["description"])]
    a["cum_count"] = np.arange(1, len(a) + 1)
    a["cum_sentiment"] = a["sentiment"].cumsum()
    cum_cols = a[["timestamp", "cum_count", "cum_sentiment"]]

    candle_time = pd.to_datetime(out["time"], utc=True)
    query_now = pd.DataFrame({"time": candle_time})
    as_of_now = pd.merge_asof(query_now, cum_cols, left_on="time", right_on="timestamp", direction="backward")

    for w in windows_minutes:
        query_start = pd.DataFrame({"time": candle_time - pd.Timedelta(minutes=w)})
        as_of_start = pd.merge_asof(
            query_start, cum_cols, left_on="time", right_on="timestamp", direction="backward"
        )

        count_in_window = (as_of_now["cum_count"].fillna(0) - as_of_start["cum_count"].fillna(0)).clip(lower=0)
        sentiment_sum_in_window = as_of_now["cum_sentiment"].fillna(0) - as_of_start["cum_sentiment"].fillna(0)
        mean_sentiment = (sentiment_sum_in_window / count_in_window.replace(0, np.nan)).fillna(0.0)

        out[f"news_count_{w}m"] = count_in_window.to_numpy().astype(int)
        out[f"news_sentiment_{w}m"] = mean_sentiment.to_numpy()
        out[f"news_sentiment_abs_{w}m"] = mean_sentiment.abs().to_numpy()

    return out


def news_feature_columns(windows_minutes: tuple[int, ...] = DEFAULT_WINDOWS_MINUTES) -> list[str]:
    cols = []
    for w in windows_minutes:
        cols += [f"news_count_{w}m", f"news_sentiment_{w}m", f"news_sentiment_abs_{w}m"]
    return cols
