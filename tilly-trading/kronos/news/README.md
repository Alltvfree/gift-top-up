# Kronos news pipeline

Turns news headlines into numerical features Kronos's own model can train
on — article count and sentiment in rolling time windows — using a
**local trained ML classifier**, not a cloud LLM API. That was a deliberate
choice (see "Why local, not a paid API" below), made explicitly after
reviewing what platforms like Elirox/Trade Ideas actually do (paid news
API + GPT-4o-mini/Claude Haiku sentiment scoring) and choosing a
self-hosted alternative instead: no subscription, no API key, no per-call
cost, nothing running outside your own VPS.

Separate from `backend/app/services/news_filter.py` and the `news_events`
Supabase table — those are about a scheduled ECONOMIC CALENDAR (NFP, CPI,
rate decisions) used to pause bot entries near high-impact releases. This
package is a different concern: turning article TEXT into features for
Kronos's own model, stored locally in `news/data/`, never in Supabase.

## The one thing to understand before using this

**This can only ever have *forward* coverage.** `collect_news.py` starts
building real history the first time you run it — there is no free way to
retroactively backfill months of historical news for a backtest, short of
a paid historical news archive. That means:

- **`backtest/walk_forward.py` deliberately does NOT use news features.**
  A walk-forward test window from before you started collecting has ZERO
  real news coverage, so a news feature would read as 0 for nearly all of
  history and only become real in the most recent slice — not a fair test
  of whether it helps, just a feature that's usually absent dressed up as
  one that's usually neutral. See `train.prepare_dataset`'s own docstring.
- News features are for **`infer.py`'s live predictions**, and for
  **retraining once you've collected enough real history** (a few weeks,
  realistically) that a model trained on it is learning from genuine
  coverage, not mostly-zero padding.

If you want news features backtested against real history, the honest
path is a paid historical news/sentiment API — not something to fake with
what this package collects going forward.

## Setup

1. **Train the local sentiment classifier** (one-off, ~1 second, pure
   scikit-learn — already installed, no new dependency):
   ```powershell
   cd C:\tilly-kronos
   python -m news.train_sentiment_model
   ```
   This trains on a small SYNTHETIC dataset we authored ourselves (see
   `generate_training_data.py` — template headlines built from a curated
   bullish/bearish vocabulary, including negated examples like "fails to
   rally despite strong demand" so the model learns what a flat keyword
   lookup can't). It is NOT real news, and the printed test accuracy
   (often ~1.0) is a sanity check that training works, not a real-world
   accuracy estimate — the templates are close enough to each other that
   near-perfect separation is expected and means nothing. Until this step
   runs, `news/sentiment.py` falls back automatically to a rule-based
   lexicon scorer (still fully functional, just cruder — see that file's
   own docstring for exactly what it can't do that the trained model can).

2. **Start collecting news**, on a schedule (a Windows Scheduled Task,
   same pattern as everything else in this project — though this one
   doesn't need MT5 IPC, so no `-LogonType Interactive` requirement):
   ```powershell
   python collect_news.py --interval-minutes 30
   ```
   > The default feed list in `collect_news.py` is **unverified from this
   > development environment** — its network is locked to an allowlist of
   > package registries, so ordinary websites return 403 before a request
   > even reaches them. `news/rss.py`'s parsing was tested against
   > hand-built synthetic RSS/Atom XML (`tests/test_news.py`), never
   > against these real URLs. Confirm each feed actually returns valid
   > RSS/Atom from the VPS before trusting it; swap in your own feeds
   > freely — nothing else hardcodes this list.

3. **Wait** — realistically a few weeks — for `news/data/articles.jsonl`
   to accumulate real, meaningfully-varied coverage.

4. **Train with news features**:
   ```powershell
   python train.py --symbol BTCUSDm --timeframe M5 --side BUY --tp 300 --sl 200 --news-store news/data/articles.jsonl --out kronos_model_buy.txt
   python train.py --symbol BTCUSDm --timeframe M5 --side SELL --tp 300 --sl 200 --news-store news/data/articles.jsonl --out kronos_model_sell.txt
   ```
   Read the printed AUC same as any other run — a news-augmented model
   isn't assumed better just because it has more features.

5. **Run inference with the matching `--news-store`** (must match what
   both models were trained with, or `predict()` fails loudly on a
   missing column rather than mispredicting silently):
   ```powershell
   python infer.py --model-buy kronos_model_buy.txt --model-sell kronos_model_sell.txt --news-store news/data/articles.jsonl ...
   ```

## Why local, not a paid API

A paid news API (TradingEconomics, Financial Modeling Prep, Benzinga,
CryptoPanic) plus a cloud LLM for sentiment (GPT-4o-mini, Claude Haiku) is
what sophisticated retail bots actually use, and it's a genuinely better
signal than what's here — real news coverage instead of RSS scraping, and
real language understanding instead of TF-IDF + logistic regression. That
tradeoff was made explicitly, not by default: it costs a real recurring
subscription and an API key that has to be created, funded, and kept
secret, for a signal the live trading loop depends on. This package trades
some signal quality for zero cost, zero external credentials, and nothing
running outside your own VPS. Swapping in a paid API later is a contained
change — mainly `news/rss.py` (fetch) and `news/sentiment.py`
(`score_text`, called once with an article's text) — since every other
file downstream (features.py, train.py, infer.py) only ever consumes a
[-1, 1] score and article timestamps, not how they were produced.

## Files

- `sentiment.py` — `score_text(text) -> float`, [-1, 1]. Trained model
  first, rule-based lexicon fallback (see both docstrings).
- `train_sentiment_model.py` — trains and saves the local classifier.
- `generate_training_data.py` — the synthetic, self-authored training set.
- `rss.py` — stdlib-only (no `feedparser`) RSS/Atom fetching and parsing.
- `store.py` — local JSONL article store, append-only, deduped by URL.
- `features.py` — `attach_news_features()`: timestamp-safe (genuinely
  time-windowed, not row-count-windowed — see its own docstring for the
  bug in a reviewed reference implementation this fixes), causal by
  construction (never sees a future article).
- `../collect_news.py` — the polling script (top-level, matches
  `train.py`/`infer.py`'s convention of living at the kronos/ root).

Tested against synthetic data and hand-built RSS/Atom XML (`tests/
test_news.py`, run with `pytest` from `kronos/`) — real feed connectivity
has not been verified from this development environment (see the warning
above); real training/inference against collected articles has, via an
end-to-end test that trains a model with news features and predicts with
it through `infer.latest_signal`.
