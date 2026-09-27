"""Trains news/sentiment.py's local ML sentiment classifier — TF-IDF +
logistic regression over a synthetic, self-authored headline dataset (see
generate_training_data.py). Run this once after setup, and again any time
you want to regenerate the dataset or retrain:

    python -m news.train_sentiment_model

Saves to news/models/sentiment_model.joblib. sentiment.py loads this file
lazily and falls back to the rule-based lexicon scorer (with one printed
warning) if it isn't there yet — so nothing breaks before you've trained
it, but you should train it before relying on sentiment features for
anything real.

Only scikit-learn is needed (TfidfVectorizer, LogisticRegression, joblib
all ship with it) — already installed and confirmed working on the VPS,
so this adds no new dependency risk.
"""
from __future__ import annotations

from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

from .generate_training_data import generate_dataset
from .sentiment import MODEL_PATH


def train_and_save(out_path: Path = MODEL_PATH, seed: int = 42) -> dict:
    rows = generate_dataset(seed=seed)
    texts = [r[0] for r in rows]
    labels = [r[1] for r in rows]

    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=seed, stratify=labels
    )

    pipeline = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1)),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    )
    pipeline.fit(x_train, y_train)
    accuracy = pipeline.score(x_test, y_test)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, out_path)
    return {"train_rows": len(x_train), "test_rows": len(x_test), "test_accuracy": accuracy, "path": str(out_path)}


def main() -> None:
    metrics = train_and_save()
    print(
        f"Trained sentiment model on {metrics['train_rows']} rows, "
        f"test accuracy {metrics['test_accuracy']:.3f} on {metrics['test_rows']} held-out rows."
    )
    print(f"Saved to {metrics['path']}")
    print(
        "This is a small SYNTHETIC dataset (see generate_training_data.py) — "
        "treat this accuracy as a sanity check that training works, not as "
        "real-world sentiment accuracy. See news/README.md."
    )


if __name__ == "__main__":
    main()
