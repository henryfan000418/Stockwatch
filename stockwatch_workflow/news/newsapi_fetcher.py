from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from stockwatch_workflow.models import NewsItem
from stockwatch_workflow.news.rss_fetcher import extract_tickers, extract_industries


def fetch_newsapi_news(config: dict[str, Any]) -> list[NewsItem]:
    """Fetch news from NewsAPI.org. Requires NEWSAPI_KEY env var and news_api.enabled: true."""
    api_cfg = config.get("news_api", {})
    if not api_cfg.get("enabled", False):
        return []

    api_key = os.getenv("NEWSAPI_KEY", "")
    if not api_key:
        return []

    try:
        from newsapi import NewsApiClient  # type: ignore
    except ImportError:
        return []

    client = NewsApiClient(api_key=api_key)
    max_articles = api_cfg.get("max_articles", 100)
    days_back = api_cfg.get("days_back", 1)

    # Build query from industry keywords to maximize relevance
    industry_keywords = config.get("discovery", {}).get("industry_keywords", {})
    top_terms = []
    for keywords in industry_keywords.values():
        top_terms.extend(keywords[:2])
    query = " OR ".join(top_terms[:10]) if top_terms else "stock market"

    items: list[NewsItem] = []
    try:
        response = client.get_everything(
            q=query,
            language="en",
            sort_by="publishedAt",
            page_size=min(max_articles, 100),
        )
        articles = response.get("articles", [])
    except Exception:
        return []

    for article in articles:
        title = (article.get("title") or "").strip()
        summary = (article.get("description") or "").strip()
        url = (article.get("url") or "").strip()
        source_name = article.get("source", {}).get("name", "NewsAPI")
        published_at = None
        raw_date = article.get("publishedAt")
        if raw_date:
            try:
                published_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                pass

        text = f"{title} {summary}"
        items.append(
            NewsItem(
                title=title,
                source=f"NewsAPI/{source_name}",
                url=url,
                published_at=published_at,
                summary=summary,
                tickers=extract_tickers(text),
                sectors=extract_industries(text, config),
            )
        )

    return items
