"""News sentiment scoring.

Primary path: a LOCAL trained ML classifier (TF-IDF + logistic regression,
via scikit-learn — already installed and working on the VPS, so no new
dependency risk) — see train_sentiment_model.py. Deliberately not a cloud
LLM API (no OpenAI/Anthropic key, no subscription, no per-call cost, no
external dependency for a signal the trading system runs on) and not
`transformers`/`torch` either (this VPS has already failed to install two
ordinary packages — matplotlib, PyYAML — for lack of a C compiler and a
prebuilt wheel; a multi-GB local LLM install is a much bigger version of
that same risk, not a safe default here).

Fallback path: score_text() below (`_lexicon_score`), used automatically
whenever the trained model hasn't been produced yet (run
`python -m news.train_sentiment_model` once to train it) or fails to load.
A hand-curated bullish/bearish word list with negation and intensifier
handling — meaningfully better than a naive keyword-count baseline (a
~30-word list with no negation handling was reviewed alongside this one:
"gold support levels didn't hold, no signs of a rally" would score
strongly POSITIVE under that scheme purely from "support"/"rally"
appearing, with "didn't"/"no" doing nothing) — but still a rule-based
proxy, not a model. It exists so this package never returns nothing before
you've trained the real model, or if loading it ever fails at runtime.
"""
from __future__ import annotations

import re
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / "models" / "sentiment_model.joblib"

# Deliberately broader than a generic finance lexicon — covers macro,
# crypto, and gold-specific vocabulary since Kronos trades BTCUSD/XAUUSD.
# Ambiguous/context-dependent words (e.g. "hawkish", "volatility", "cut")
# are left out on purpose rather than guessed at with a fixed polarity.
POSITIVE = {
    "rally", "rallies", "rallied", "rallying",
    "surge", "surges", "surged", "surging",
    "soar", "soars", "soared", "soaring",
    "jump", "jumps", "jumped",
    "gain", "gains", "gained",
    "climb", "climbs", "climbed",
    "rise", "rises", "risen", "rising",
    "rebound", "rebounds", "rebounded",
    "recover", "recovers", "recovered", "recovery",
    "breakout", "breakthrough",
    "record", "high", "highs",
    "bullish", "optimistic", "upbeat", "positive",
    "strong", "strength", "strengthen", "strengthens", "strengthened",
    "robust", "resilient", "outperform", "outperforms", "outperformed",
    "upgrade", "upgraded", "upgrades",
    "inflow", "inflows", "accumulation", "accumulate", "accumulating",
    "adoption", "approval", "approved", "approves",
    "buy", "buying", "bought", "demand",
    "expansion", "expands", "expanding",
    "support", "supported", "holding",
    "safe-haven", "haven",
}
NEGATIVE = {
    "crash", "crashes", "crashed", "crashing",
    "plunge", "plunges", "plunged", "plunging",
    "plummet", "plummets", "plummeted",
    "slump", "slumps", "slumped",
    "tumble", "tumbles", "tumbled",
    "drop", "drops", "dropped", "dropping",
    "fall", "falls", "fell", "falling",
    "decline", "declines", "declined",
    "selloff", "sell-off",
    "correction", "pullback",
    "bearish", "pessimistic", "negative",
    "weak", "weakness", "weaken", "weakens", "weakened",
    "recession", "contraction", "contracting",
    "default", "bankruptcy", "bankrupt", "insolvent",
    "hack", "hacked", "hacker", "exploit", "exploited",
    "scam", "fraud", "fraudulent",
    "lawsuit", "sued", "sues", "litigation",
    "ban", "banned", "banning", "restriction", "restricted",
    "outflow", "outflows",
    "liquidation", "liquidations", "liquidated",
    "panic", "fear", "uncertainty",
    "downgrade", "downgraded", "downgrades",
    "underperform", "underperforms", "underperformed",
    "layoffs", "layoff",
    "warning", "warns", "warned",
    "rejection", "rejected", "resistance",
}
NEGATIONS = {"not", "no", "never", "without", "n't", "neither", "nor", "none"}
INTENSIFIERS = {"very", "highly", "sharply", "significantly", "massively", "extremely"}
NEGATION_WINDOW = 3  # how many preceding tokens can flip a sentiment word's polarity


def _lexicon_score(text: str) -> float:
    """Returns a score in [-1, 1]. 0.0 for empty/neutral text — never NaN,
    so this is always safe to feed straight into a rolling mean."""
    words = re.findall(r"[a-zA-Z']+", (text or "").lower())
    if not words:
        return 0.0

    total = 0.0
    for i, word in enumerate(words):
        polarity = 1.0 if word in POSITIVE else -1.0 if word in NEGATIVE else 0.0
        if polarity == 0.0:
            continue

        window = words[max(0, i - NEGATION_WINDOW):i]
        if any(w in NEGATIONS or w.endswith("n't") for w in window):
            polarity *= -1.0
        if any(w in INTENSIFIERS for w in window):
            polarity *= 1.5

        total += polarity

    # Dampen by sqrt of article length, floor at 5 words so a short
    # headline with one strong word doesn't saturate to +-1.
    return max(-1.0, min(1.0, total / max(5, len(words) ** 0.5)))


_model = None
_model_load_attempted = False


def _load_model():
    global _model, _model_load_attempted
    if _model_load_attempted:
        return _model
    _model_load_attempted = True
    if not MODEL_PATH.exists():
        print(
            f"[news.sentiment] No trained model at {MODEL_PATH} yet — falling back to the "
            "rule-based lexicon scorer. Run `python -m news.train_sentiment_model` to train it."
        )
        return None
    try:
        import joblib

        _model = joblib.load(MODEL_PATH)
    except Exception as exc:  # noqa: BLE001 - any load failure should fall back, never crash the caller
        print(f"[news.sentiment] Failed to load trained sentiment model ({exc}) — falling back to lexicon.")
    return _model


def score_text(text: str) -> float:
    """Returns a score in [-1, 1]. Uses the trained local classifier when
    available (see this module's docstring), otherwise the rule-based
    lexicon fallback. Never raises and never returns NaN — always safe to
    feed straight into a rolling mean."""
    text = text or ""
    model = _load_model()
    if model is not None:
        try:
            proba = model.predict_proba([text])[0]
            classes = list(model.classes_)
            p_bear = float(proba[classes.index(-1)]) if -1 in classes else 0.0
            p_bull = float(proba[classes.index(1)]) if 1 in classes else 0.0
            return max(-1.0, min(1.0, p_bull - p_bear))
        except Exception as exc:  # noqa: BLE001 - a bad prediction should fall back, never crash the caller
            print(f"[news.sentiment] Trained model prediction failed ({exc}) — falling back to lexicon for this call.")
    return _lexicon_score(text)
