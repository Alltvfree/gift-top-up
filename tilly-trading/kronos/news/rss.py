"""RSS/Atom feed fetching — standard library only (urllib + xml.etree), no
`feedparser` dependency. This project has already hit wheel-availability
failures twice on the VPS's Python version (see requirements.txt's notes on
matplotlib/PyYAML) — RSS/Atom parsing doesn't need a third-party library to
add that same risk a third time.

Deliberately minimal: handles the common RSS 2.0 <item> and Atom <entry>
shapes, not the full spec. A feed that fails to fetch or parse raises —
collect_news.py decides per-feed whether that should stop the whole poll
cycle (it doesn't: one bad feed is logged and skipped).
"""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import pandas as pd

USER_AGENT = "Mozilla/5.0 (compatible; KronosNewsBot/1.0)"
TIMEOUT_SECONDS = 15
ATOM_NS = "{http://www.w3.org/2005/Atom}"


@dataclass
class Article:
    timestamp: pd.Timestamp
    title: str
    description: str
    source: str
    url: str


def fetch_feed(url: str, source_name: str) -> list[Article]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 - fixed http(s) feed URLs, not user input
        raw = resp.read()
    return parse_feed(raw, source_name)


def parse_feed(raw: bytes, source_name: str) -> list[Article]:
    root = ET.fromstring(raw)

    channel_items = root.findall("./channel/item")
    if channel_items:
        return [_parse_rss_item(item, source_name) for item in channel_items]

    entries = root.findall(f"{ATOM_NS}entry")
    return [_parse_atom_entry(entry, source_name) for entry in entries]


def _text(el, tag: str) -> str:
    node = el.find(tag)
    return (node.text or "").strip() if node is not None and node.text else ""


def _parse_rss_item(item, source_name: str) -> Article:
    return Article(
        timestamp=_parse_datetime(_text(item, "pubDate"), iso=False),
        title=_text(item, "title"),
        description=_text(item, "description"),
        source=source_name,
        url=_text(item, "link"),
    )


def _parse_atom_entry(entry, source_name: str) -> Article:
    link_el = entry.find(f"{ATOM_NS}link")
    link = link_el.get("href", "") if link_el is not None else ""
    return Article(
        timestamp=_parse_datetime(
            _text(entry, f"{ATOM_NS}updated") or _text(entry, f"{ATOM_NS}published"), iso=True
        ),
        title=_text(entry, f"{ATOM_NS}title"),
        description=_text(entry, f"{ATOM_NS}summary") or _text(entry, f"{ATOM_NS}content"),
        source=source_name,
        url=link,
    )


def _parse_datetime(raw: str, iso: bool) -> pd.Timestamp:
    # A fallback to "now" on a missing/malformed timestamp is deliberate:
    # it treats an unparseable article as freshly arrived rather than
    # guessing a past time for it — the safe direction to be wrong in,
    # since backdating an article could make it look like it was known
    # earlier than it really was.
    if not raw:
        return pd.Timestamp.now(tz="UTC")
    try:
        ts = pd.Timestamp(raw) if iso else pd.Timestamp(parsedate_to_datetime(raw))
    except (ValueError, TypeError):
        return pd.Timestamp.now(tz="UTC")
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
