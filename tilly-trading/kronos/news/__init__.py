"""News collection and feature engineering for Kronos.

Separate from `backend/app/services/news_filter.py` and the `news_events`
Supabase table — those are about a scheduled ECONOMIC CALENDAR (NFP, CPI,
rate decisions) used to pause bot entries near high-impact releases. This
package is a different concern entirely: turning ARTICLE TEXT (headlines
from RSS feeds) into numerical features Kronos's own model can train on —
sentiment, article volume, recency — stored locally, never in Supabase.

Read news/README.md before using this — in particular, it can only ever
have *forward* coverage (collection starts whenever you first run it), so
it cannot be used to backtest against history without a paid news archive.
"""
