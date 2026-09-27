"""Polls a configured list of RSS feeds and appends new articles to the
local JSONL store (news/data/articles.jsonl by default).

> **Feed URLs below are UNVERIFIED from this development environment.**
> This project's outbound network here is restricted to an allowlist of
> package registries (pypi, npm, github, ...) — ordinary websites return
> 403 before a request ever reaches them, so news/rss.py's parsing logic
> was tested against hand-built synthetic RSS/Atom XML (see
> tests/test_news.py), never against these real URLs. Confirm each feed
> actually returns valid RSS/Atom from the VPS (which has normal internet
> access) before relying on this — same caveat as mt5_data.py's own real
> MT5 calls, or bridge.py's: written and reviewed carefully, not run for
> real here.

Run this on a schedule (a Windows Scheduled Task, same pattern as every
other always-on piece of this project — though unlike bridge.py/infer.py,
this one doesn't need MT5 IPC, so it doesn't need -LogonType Interactive):

    python collect_news.py --interval-minutes 30

Or once, for testing:

    python collect_news.py --once
"""
from __future__ import annotations

import time

from news.rss import fetch_feed
from news.store import append_articles

# Suggested starting set — free, no API key. Verify on the VPS before
# trusting them (see this file's module docstring). Add/remove freely;
# nothing else in this project hardcodes this list.
DEFAULT_FEEDS = [
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
    ("https://cointelegraph.com/rss", "Cointelegraph"),
    ("https://www.fxstreet.com/rss/news", "FXStreet"),
    ("https://www.investing.com/rss/news_285.rss", "Investing.com Commodities"),
]

DEFAULT_STORE_PATH = "news/data/articles.jsonl"


def poll_once(feeds: list[tuple[str, str]], store_path: str) -> dict:
    """Fetches every configured feed once. A single bad feed is logged and
    skipped — never allowed to crash the whole poll cycle (same philosophy
    as infer.py's run_loop: one bad cycle/feed shouldn't kill the process).
    Returns {source_name: new_article_count}."""
    results = {}
    for url, source_name in feeds:
        try:
            articles = fetch_feed(url, source_name)
            new_count = append_articles(store_path, articles)
            results[source_name] = new_count
            print(f"[{source_name}] fetched {len(articles)}, {new_count} new")
        except Exception as exc:  # noqa: BLE001 - one feed failing must not stop the others
            print(f"[{source_name}] failed: {exc}")
            results[source_name] = -1
    return results


def run_loop(feeds: list[tuple[str, str]], store_path: str, interval_minutes: int) -> None:
    while True:
        poll_once(feeds, store_path)
        time.sleep(interval_minutes * 60)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=DEFAULT_STORE_PATH)
    parser.add_argument("--interval-minutes", type=int, default=30)
    parser.add_argument("--once", action="store_true", help="Fetch every feed once and exit, instead of looping.")
    args = parser.parse_args()

    if args.once:
        poll_once(DEFAULT_FEEDS, args.store)
    else:
        run_loop(DEFAULT_FEEDS, args.store, args.interval_minutes)


if __name__ == "__main__":
    main()
