from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from stockwatch_workflow.models import NewsItem
from stockwatch_workflow.news.rss_fetcher import extract_tickers, extract_industries

_REDDIT_HEADERS = {"User-Agent": "stockwatch-bot/1.0"}
_REDDIT_URL = "https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"


def fetch_reddit_news(config: dict[str, Any]) -> list[NewsItem]:
    """Fetch posts from finance subreddits via Reddit's public JSON API. No OAuth needed."""
    reddit_cfg = config.get("reddit", {})
    if not reddit_cfg.get("enabled", False):
        return []

    subreddits = reddit_cfg.get("subreddits", ["investing", "stocks", "SecurityAnalysis"])
    max_posts = reddit_cfg.get("max_posts", 30)
    items: list[NewsItem] = []

    for subreddit in subreddits:
        try:
            resp = requests.get(
                _REDDIT_URL.format(subreddit=subreddit, limit=max_posts),
                headers=_REDDIT_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
        except Exception:
            continue

        for post in posts:
            data = post.get("data", {})
            title = (data.get("title") or "").strip()
            summary = (data.get("selftext") or "")[:500].strip()
            url = data.get("url") or f"https://reddit.com{data.get('permalink', '')}"
            created_utc = data.get("created_utc")
            published_at = (
                datetime.fromtimestamp(created_utc, tz=timezone.utc) if created_utc else None
            )
            text = f"{title} {summary}"
            items.append(
                NewsItem(
                    title=title,
                    source=f"Reddit/r/{subreddit}",
                    url=url,
                    published_at=published_at,
                    summary=summary,
                    tickers=extract_tickers(text),
                    sectors=extract_industries(text, config),
                )
            )

    return items
