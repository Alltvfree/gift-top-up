"""news/ package tests — sentiment scoring (lexicon fallback + trained
model), RSS/Atom parsing against hand-built synthetic XML (no real network
call — see collect_news.py's own caveat about this sandbox's restricted
network), the article store's URL dedup, and the timestamp-safe (not
row-count-safe) feature attachment this package was built to get right.
"""
import pandas as pd
import pytest

import news.sentiment as sentiment_module
from news.features import attach_news_features
from news.rss import parse_feed
from news.sentiment import _lexicon_score, score_text
from news.store import append_articles, load_articles


@pytest.fixture(autouse=True)
def _reset_model_cache():
    """sentiment.py caches the loaded model in module globals — reset
    between tests so one test's monkeypatched MODEL_PATH can't leak into
    another's."""
    sentiment_module._model = None
    sentiment_module._model_load_attempted = False
    yield
    sentiment_module._model = None
    sentiment_module._model_load_attempted = False


def test_lexicon_score_handles_negation():
    positive = _lexicon_score("Gold rallies on strong demand")
    negated = _lexicon_score("Gold did not rally despite strong demand")
    assert positive > 0
    assert negated < positive
    assert negated <= 0, "negation should flip a positive-word headline toward bearish, not just dampen it"


def test_lexicon_score_neutral_and_empty():
    assert _lexicon_score("") == 0.0
    assert _lexicon_score("Gold price steady in quiet Asian session") == pytest.approx(0.0, abs=0.2)


def test_lexicon_score_never_nan_or_out_of_range():
    for text in ["", "   ", "asdkjaslkdj", "Gold " * 50 + "crashes", None]:
        s = _lexicon_score(text)
        assert -1.0 <= s <= 1.0
        assert s == s  # not NaN


def test_score_text_falls_back_to_lexicon_when_no_model_trained(tmp_path, monkeypatch):
    monkeypatch.setattr(sentiment_module, "MODEL_PATH", tmp_path / "does_not_exist.joblib")
    s = score_text("Gold crashes on regulatory concerns")
    assert s < 0  # still works, via the lexicon fallback


def test_score_text_uses_trained_model_when_available(tmp_path, monkeypatch):
    from news.train_sentiment_model import train_and_save

    model_path = tmp_path / "sentiment_model.joblib"
    train_and_save(out_path=model_path)
    monkeypatch.setattr(sentiment_module, "MODEL_PATH", model_path)

    bullish = score_text("Gold rallies as strong demand boosts sentiment")
    bearish = score_text("Bitcoin crashes on regulatory concerns")
    negated = score_text("Gold fails to rally despite strong demand")
    assert bullish > 0.3
    assert bearish < -0.3
    assert negated < 0, "the trained model must handle negation the pure lexicon can't"


RSS_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Gold rallies as strong demand boosts sentiment</title>
<description>Some description here.</description>
<link>https://example.com/article1</link>
<pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
</item>
<item>
<title>Bitcoin crashes on regulatory concerns</title>
<description>Another description.</description>
<link>https://example.com/article2</link>
<pubDate>Mon, 01 Jan 2024 11:30:00 GMT</pubDate>
</item>
</channel></rss>"""

ATOM_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
<title>Gold trades flat ahead of Fed decision</title>
<summary>Some summary.</summary>
<link href="https://example.com/article3"/>
<updated>2024-01-01T12:00:00Z</updated>
</entry>
</feed>"""


def test_parse_rss_feed():
    articles = parse_feed(RSS_XML, "TestSource")
    assert len(articles) == 2
    assert articles[0].title == "Gold rallies as strong demand boosts sentiment"
    assert articles[0].url == "https://example.com/article1"
    assert articles[0].source == "TestSource"
    assert articles[0].timestamp == pd.Timestamp("2024-01-01 10:00:00", tz="UTC")
    assert articles[1].timestamp == pd.Timestamp("2024-01-01 11:30:00", tz="UTC")


def test_parse_atom_feed():
    articles = parse_feed(ATOM_XML, "TestAtomSource")
    assert len(articles) == 1
    assert articles[0].title == "Gold trades flat ahead of Fed decision"
    assert articles[0].url == "https://example.com/article3"
    assert articles[0].timestamp == pd.Timestamp("2024-01-01 12:00:00", tz="UTC")


def test_store_append_and_dedup_by_url(tmp_path):
    path = tmp_path / "articles.jsonl"
    articles = parse_feed(RSS_XML, "TestSource")

    added = append_articles(path, articles)
    assert added == 2

    added_again = append_articles(path, articles)  # same URLs again
    assert added_again == 0, "re-appending the same articles must not duplicate them"

    df = load_articles(path)
    assert len(df) == 2
    assert df["timestamp"].is_monotonic_increasing


def test_load_articles_missing_file_returns_empty_frame(tmp_path):
    df = load_articles(tmp_path / "nope.jsonl")
    assert df.empty
    assert "timestamp" in df.columns


def _candles(n, freq="5min", start="2024-01-01 00:00"):
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=n, freq=freq, tz="UTC"),
            "open": [100.0] * n, "high": [100.5] * n, "low": [99.5] * n, "close": [100.0] * n,
        }
    )


def test_attach_news_features_no_articles_is_all_zero():
    candles = _candles(5)
    out = attach_news_features(candles, pd.DataFrame(columns=["timestamp", "title", "description"]))
    assert (out["news_count_15m"] == 0).all()
    assert (out["news_sentiment_15m"] == 0.0).all()


def test_attach_news_features_is_causal_no_future_article_leaks_backward():
    candles = _candles(10)  # 00:00 through 00:45, 5-min bars
    articles = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2024-01-01 00:37", tz="UTC")],  # arrives after most candles
            "title": ["Bitcoin crashes on regulatory concerns"],
            "description": [""],
        }
    )
    out = attach_news_features(candles, articles, windows_minutes=(240,))
    before = out[out["time"] < "2024-01-01 00:37+00:00"]
    assert (before["news_count_240m"] == 0).all(), "a candle before the article's timestamp must not see it"
    after = out[out["time"] >= "2024-01-01 00:37+00:00"]
    assert (after["news_count_240m"] == 1).all()


def test_attach_news_features_window_is_time_based_not_row_count():
    """The exact bug this module fixes: on H1 candles, a 60-minute window
    must cover exactly ONE bar's worth of time, not N rows regardless of
    spacing (the reference implementation's `.rolling(window=w)` bug)."""
    candles = _candles(5, freq="1h")  # 00:00, 01:00, 02:00, 03:00, 04:00
    articles = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2024-01-01 01:30", tz="UTC")],
            "title": ["Gold rallies as strong demand boosts sentiment"],
            "description": [""],
        }
    )
    out = attach_news_features(candles, articles, windows_minutes=(60,))
    # The article (01:30) is > 60 minutes before the 03:00 and 04:00 candles,
    # so a genuinely time-based 60-minute window must have rolled it off by
    # then — a row-count-based window (as in the reference bug) would still
    # show it for several more rows regardless of the 1-hour spacing.
    counts = out.set_index(out["time"].dt.strftime("%H:%M"))["news_count_60m"]
    assert counts["02:00"] == 1  # within 60 minutes of 01:30
    assert counts["03:00"] == 0  # 90 minutes after 01:30 — must have rolled off
    assert counts["04:00"] == 0


def test_attach_news_features_sentiment_matches_score_text():
    candles = _candles(3)
    articles = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2024-01-01 00:02", tz="UTC")],
            "title": ["Gold rallies as strong demand boosts sentiment"],
            "description": [""],
        }
    )
    out = attach_news_features(candles, articles, windows_minutes=(15,))
    expected = score_text("Gold rallies as strong demand boosts sentiment ")
    assert out["news_sentiment_15m"].iloc[1] == pytest.approx(expected, abs=1e-6)


def test_train_and_infer_wire_news_features_end_to_end(tmp_path):
    """train.prepare_dataset(news_articles=...) and infer.latest_signal
    (news_store_path=...) must produce the exact same feature-column set,
    or predict() would fail on a mismatch — this proves they actually do,
    not just that each half works in isolation."""
    from conftest import make_synthetic_ohlc

    import infer
    from train import feature_columns_for, prepare_dataset, train_model

    base_raw = make_synthetic_ohlc(3000, freq="5min", seed=7)
    articles = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=20, freq="3h", tz="UTC"),
            "title": ["Gold rallies as strong demand boosts sentiment"] * 10
            + ["Bitcoin crashes on regulatory concerns"] * 10,
            "description": [""] * 20,
        }
    )
    news_windows = (15, 60, 240)

    dataset = prepare_dataset(
        base_raw, side="BUY", tp_distance=3.0, sl_distance=2.0, max_bars_forward=20,
        news_articles=articles, news_windows=news_windows,
    )
    expected_cols = feature_columns_for(None, news_windows)
    for c in expected_cols:
        assert c in dataset.columns

    model, _ = train_model(dataset, feature_columns=expected_cols)
    model_path = tmp_path / "buy_model.txt"
    model.save_model(str(model_path))

    news_path = tmp_path / "articles.jsonl"
    news_path.write_text(
        "\n".join(
            f'{{"timestamp": "{ts.isoformat()}", "title": "{t}", "description": "", '
            f'"source": "test", "url": "https://example.com/{i}"}}'
            for i, (ts, t) in enumerate(zip(articles["timestamp"], articles["title"]))
        )
    )

    def fake_download_history(symbol, timeframe, bars):
        return make_synthetic_ohlc(max(bars, 300), freq="5min", start_time="2024-06-01", seed=7)

    original = infer.download_history
    infer.download_history = fake_download_history
    try:
        model_buy = infer.lgb.Booster(model_file=str(model_path))
        signal = infer.latest_signal(
            model_buy, model_buy, "XAUUSDm", "M5", lookback_bars=300,
            news_store_path=str(news_path), news_windows=news_windows,
        )
    finally:
        infer.download_history = original

    assert signal["side"] in ("BUY", "SELL", "NO_TRADE")
