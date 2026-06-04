from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

import feedparser

from stockwatch_workflow.models import NewsItem


EXPLICIT_TICKER_PATTERNS = (
    re.compile(r"\$([A-Z]{1,5})(?![A-Z])"),
    re.compile(r"\b(?:NYSE|NASDAQ|Nasdaq|NasdaqGS|AMEX|OTC)\s*:\s*([A-Z.]{1,5})\b"),
    re.compile(r"\(([A-Z]{1,5})\)"),
    re.compile(
        r"\b([A-Z]{2,5})\s+(?:Corporation|Corp\.?|Inc\.?|Ltd\.?|PLC|Holdings?|Group|Technologies|Enterprise|Enterprises)\b"
    ),
)
COMMON_FALSE_TICKERS = {
    "AI", "CEO", "CFO", "SEC", "USA", "US", "FED", "ETF", "IPO",
    "GDP", "EPS", "NYSE", "NASDAQ",
}


def clean_text(value: str) -> str:
    return " ".join(unescape(value or "").strip().split())


def extract_tickers(text: str) -> tuple[str, ...]:
    candidates: set[str] = set()
    for pattern in EXPLICIT_TICKER_PATTERNS:
        for match in pattern.finditer(text):
            ticker = match.group(1).replace(".", "-").upper()
            if ticker not in COMMON_FALSE_TICKERS:
                candidates.add(ticker)
    return tuple(sorted(candidates))


def extract_industries(text: str, config: dict[str, Any]) -> tuple[str, ...]:
    lowered = text.lower()
    industry_keywords = config.get("discovery", {}).get("industry_keywords", {})
    matched = []
    for industry, keywords in industry_keywords.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            matched.append(industry)
    return tuple(matched)


def fetch_rss_news(config: dict[str, Any]) -> list[NewsItem]:
    items: list[NewsItem] = []
    for source in config.get("sources", {}).get("news", []):
        if source.get("type") != "rss":
            continue
        try:
            feed = feedparser.parse(source["url"])
        except Exception:
            continue
        for entry in feed.entries[:25]:
            published = None
            if getattr(entry, "published_parsed", None):
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            title = clean_text(entry.get("title", ""))
            summary = clean_text(entry.get("summary", ""))
            text = f"{title} {summary}"
            tickers = extract_tickers(text) if source.get("extract_tickers", True) else ()
            items.append(
                NewsItem(
                    title=title,
                    source=source["name"],
                    url=entry.get("link", "").strip(),
                    published_at=published,
                    summary=summary,
                    tickers=tickers,
                    sectors=extract_industries(text, config),
                )
            )
    return items
