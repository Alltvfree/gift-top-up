"""Generates a synthetic, self-authored (not scraped) labeled headline
dataset to train news/sentiment.py's local classifier on.

Entirely our own text — template sentences built from domain vocabulary,
not copied from any real news source or third-party corpus — so there's no
dataset-licensing question the way redistributing a scraped or academic
corpus would raise. Small and crude by construction (a genuinely large,
human-labeled corpus would train a meaningfully better model — see this
package's README for that tradeoff spelled out), but it teaches the
classifier something a flat keyword lookup can't: which WORD COMBINATIONS
(via TF-IDF bigrams) tend to flip a headline's sentiment, including
negation ("fails to rally", "no signs of recovery") that a bag-of-words
lexicon score misses entirely.
"""
from __future__ import annotations

import random

ASSETS = ["Gold", "XAUUSD", "Bitcoin", "BTCUSD", "crypto markets", "the dollar", "risk assets"]

BULLISH_VERBS = [
    "rallies", "surges", "jumps", "climbs", "soars", "rebounds", "breaks out", "gains", "extends gains",
]
BEARISH_VERBS = [
    "plunges", "tumbles", "slumps", "drops", "falls", "sinks", "sells off", "extends losses", "crashes",
]

BULLISH_REASONS = [
    "strong demand", "a weaker dollar", "safe-haven buying", "positive economic data",
    "renewed investor optimism", "a dovish policy outlook", "robust institutional inflows",
    "growing adoption", "better than expected earnings",
]
BEARISH_REASONS = [
    "profit-taking", "a stronger dollar", "rising bond yields", "weak economic data",
    "growing investor caution", "hawkish policy signals", "heavy outflows",
    "regulatory concerns", "disappointing earnings",
]
NEUTRAL_EVENTS = [
    "the Fed's rate decision", "tomorrow's inflation report", "the jobs report",
    "next week's earnings season", "the central bank meeting",
]


def _bullish(n: int) -> list[tuple[str, int]]:
    rows = []
    for _ in range(n):
        asset, verb, reason = random.choice(ASSETS), random.choice(BULLISH_VERBS), random.choice(BULLISH_REASONS)
        text = random.choice([
            f"{asset} {verb} as {reason} boosts sentiment",
            f"{asset} {verb} on {reason}",
            f"Investors turn bullish on {asset} amid {reason}",
            f"{asset} hits fresh highs as {reason} continues",
        ])
        rows.append((text, 1))
    return rows


def _bearish(n: int) -> list[tuple[str, int]]:
    rows = []
    for _ in range(n):
        asset, verb, reason = random.choice(ASSETS), random.choice(BEARISH_VERBS), random.choice(BEARISH_REASONS)
        text = random.choice([
            f"{asset} {verb} as {reason} weighs on sentiment",
            f"{asset} {verb} on {reason}",
            f"Investors turn bearish on {asset} amid {reason}",
            f"{asset} hits fresh lows as {reason} continues",
        ])
        rows.append((text, -1))
    return rows


def _negated_bearish(n: int) -> list[tuple[str, int]]:
    """Headlines containing POSITIVE-sounding words that are overall
    bearish — specifically to teach the classifier what a flat keyword
    lookup can't handle (see sentiment.py's module docstring)."""
    rows = []
    for _ in range(n):
        asset, verb = random.choice(ASSETS), random.choice(BULLISH_VERBS)
        text = random.choice([
            f"{asset} fails to {verb.rstrip('s')} despite {random.choice(BULLISH_REASONS)}",
            f"No signs of a {asset} rebound as {random.choice(BEARISH_REASONS)} persists",
            f"{asset} {verb} attempt falls apart, support does not hold",
            f"{asset} unable to sustain {verb}, momentum fades",
        ])
        rows.append((text, -1))
    return rows


def _neutral(n: int) -> list[tuple[str, int]]:
    rows = []
    for _ in range(n):
        asset, event = random.choice(ASSETS), random.choice(NEUTRAL_EVENTS)
        text = random.choice([
            f"{asset} trades flat ahead of {event}",
            f"Analysts await {event} for {asset} direction",
            f"{asset} price little changed in quiet trading",
            f"{asset} holds steady as markets await {event}",
        ])
        rows.append((text, 0))
    return rows


def generate_dataset(seed: int = 42, per_class: int = 150) -> list[tuple[str, int]]:
    """Returns a list of (headline, label) pairs, label in {-1, 0, 1}.
    Deterministic given the same seed — reproducible training runs."""
    rng_state = random.getstate()
    random.seed(seed)
    try:
        rows = _bullish(per_class) + _bearish(per_class) + _negated_bearish(per_class // 2) + _neutral(per_class)
        random.shuffle(rows)
    finally:
        random.setstate(rng_state)  # don't leak this into the caller's own RNG state
    return rows
