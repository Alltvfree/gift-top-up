"""Local JSONL article store — one line per article, append-only, deduped
by URL. Deliberately a plain file, not Supabase: this is Kronos's own
training/inference input, not something the Tilly frontend or backend
needs to read (see news/__init__.py's docstring for how this differs from
the news_events economic-calendar table).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .rss import Article

COLUMNS = ["timestamp", "title", "description", "source", "url"]


def load_articles(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # one corrupted line shouldn't lose the rest of the file
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def append_articles(path: str | Path, articles: list[Article]) -> int:
    """Appends only articles whose URL isn't already in the store. Returns
    how many were actually new."""
    path = Path(path)
    existing_urls = set(load_articles(path)["url"]) if path.exists() else set()
    new_articles = [a for a in articles if a.url and a.url not in existing_urls]
    if not new_articles:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for a in new_articles:
            f.write(
                json.dumps(
                    {
                        "timestamp": a.timestamp.isoformat(),
                        "title": a.title,
                        "description": a.description,
                        "source": a.source,
                        "url": a.url,
                    }
                )
                + "\n"
            )
    return len(new_articles)
