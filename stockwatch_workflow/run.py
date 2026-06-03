from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from html import unescape

import feedparser
import yaml
from dotenv import load_dotenv

from stockwatch_workflow.models import NewsItem, StockCandidate


EXPLICIT_TICKER_PATTERNS = (
    re.compile(r"\$([A-Z]{1,5})(?![A-Z])"),
    re.compile(r"\b(?:NYSE|NASDAQ|Nasdaq|NasdaqGS|AMEX|OTC)\s*:\s*([A-Z.]{1,5})\b"),
    re.compile(r"\(([A-Z]{1,5})\)"),
    re.compile(
        r"\b([A-Z]{2,5})\s+(?:Corporation|Corp\.?|Inc\.?|Ltd\.?|PLC|Holdings?|Group|Technologies|Enterprise|Enterprises)\b"
    ),
)
COMMON_FALSE_TICKERS = {
    "AI",
    "CEO",
    "CFO",
    "SEC",
    "USA",
    "US",
    "FED",
    "ETF",
    "IPO",
    "GDP",
    "EPS",
    "NYSE",
    "NASDAQ",
}


def clean_text(value: str) -> str:
    return " ".join(unescape(value or "").strip().split())


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def fetch_rss_news(config: dict[str, Any]) -> list[NewsItem]:
    items: list[NewsItem] = []
    for source in config.get("sources", {}).get("news", []):
        if source.get("type") != "rss":
            continue
        feed = feedparser.parse(source["url"])
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


def extract_catalysts(text: str, config: dict[str, Any]) -> tuple[str, ...]:
    lowered = text.lower()
    keywords = config.get("discovery", {}).get("catalyst_keywords", [])
    return tuple(keyword for keyword in keywords if keyword.lower() in lowered)


def build_digest(news_items: list[NewsItem], config: dict[str, Any]) -> str:
    by_source = Counter(item.source for item in news_items)
    ticker_counts = Counter(ticker for item in news_items for ticker in item.tickers)
    industry_counts = Counter(industry for item in news_items for industry in item.sectors)
    catalyst_counts = Counter(
        catalyst
        for item in news_items
        for catalyst in extract_catalysts(f"{item.title} {item.summary}", config)
    )

    lines = [
        "# Daily Financial News Digest",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Coverage",
        "",
        f"- Articles scanned: {len(news_items)}",
        f"- Sources: {', '.join(f'{name} ({count})' for name, count in by_source.items()) or 'None'}",
        "",
        "## Discovered Target Industries",
        "",
    ]
    lines.extend(format_counter(industry_counts))
    lines.extend(["", "## Extracted Stock Tickers", ""])
    lines.extend(format_counter(ticker_counts))
    lines.extend(["", "## Catalyst Keywords", ""])
    lines.extend(format_counter(catalyst_counts))
    lines.extend(["", "## Top Headlines", ""])

    for item in news_items[:20]:
        tickers = f" [{', '.join(item.tickers)}]" if item.tickers else ""
        industries = f" ({', '.join(item.sectors)})" if item.sectors else ""
        lines.append(f"- {item.title}{tickers}{industries} - {item.source} - {item.url}")

    return "\n".join(lines) + "\n"


def format_counter(counter: Counter[str]) -> list[str]:
    if not counter:
        return ["- No strong signal found."]
    return [f"- {name}: {count}" for name, count in counter.most_common(10)]


def score_candidates(news_items: list[NewsItem], config: dict[str, Any]) -> list[StockCandidate]:
    ticker_news: dict[str, list[NewsItem]] = defaultdict(list)
    for item in news_items:
        for ticker in item.tickers:
            ticker_news[ticker].append(item)

    candidates: list[StockCandidate] = []
    for ticker, related_news in ticker_news.items():
        related_text = " ".join(f"{item.title} {item.summary}" for item in related_news)
        related_industries = Counter(industry for item in related_news for industry in item.sectors)
        related_catalysts = extract_catalysts(related_text, config)

        mention_score = min(len(related_news) * 12, 35)
        source_score = min(len({item.source for item in related_news}) * 10, 20)
        industry_score = min(sum(related_industries.values()) * 8, 20)
        catalyst_score = min(len(related_catalysts) * 7, 20)
        recency_score = score_recency(related_news)
        score = mention_score + source_score + industry_score + catalyst_score + recency_score

        headlines = "; ".join(item.title for item in related_news[:3])
        industry_label = ", ".join(name for name, _ in related_industries.most_common(3)) or "Unclassified"
        candidates.append(
            StockCandidate(
                symbol=ticker,
                company_name=ticker,
                score=round(score, 2),
                thesis=(
                    f"Ticker extracted from current news flow. Target industry/theme: {industry_label}. "
                    f"Headlines: {headlines}"
                ),
                catalysts=tuple(dict.fromkeys([*related_catalysts, *(item.title for item in related_news[:3])])),
                risks=("Candidate is discovered from news flow and requires filing, valuation, and peer validation.",),
                source_urls=tuple(item.url for item in related_news[:5] if item.url),
            )
        )

    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)


def score_recency(news_items: list[NewsItem]) -> int:
    if not news_items:
        return 0
    now = datetime.now(timezone.utc)
    newest = max((item.published_at for item in news_items if item.published_at), default=None)
    if newest is None:
        return 5
    age_hours = (now - newest).total_seconds() / 3600
    if age_hours <= 6:
        return 5
    if age_hours <= 24:
        return 3
    return 1


def write_industry_themes(news_items: list[NewsItem], config: dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / f"industry_themes_{datetime.now().date().isoformat()}.csv"
    industry_news: dict[str, list[NewsItem]] = defaultdict(list)
    for item in news_items:
        for industry in item.sectors:
            industry_news[industry].append(item)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["industry", "article_count", "catalysts", "top_headlines", "source_urls"])
        writer.writeheader()
        for industry, related_news in sorted(industry_news.items(), key=lambda entry: len(entry[1]), reverse=True):
            related_text = " ".join(f"{item.title} {item.summary}" for item in related_news)
            writer.writerow(
                {
                    "industry": industry,
                    "article_count": len(related_news),
                    "catalysts": " | ".join(extract_catalysts(related_text, config)),
                    "top_headlines": " | ".join(item.title for item in related_news[:5]),
                    "source_urls": " | ".join(item.url for item in related_news[:5] if item.url),
                }
            )
    return path


def write_watchlist(candidates: list[StockCandidate], output_dir: Path) -> Path:
    path = output_dir / f"watchlist_{datetime.now().date().isoformat()}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "company_name", "score", "thesis", "catalysts", "risks", "source_urls"],
        )
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "symbol": candidate.symbol,
                    "company_name": candidate.company_name,
                    "score": candidate.score,
                    "thesis": candidate.thesis,
                    "catalysts": " | ".join(candidate.catalysts),
                    "risks": " | ".join(candidate.risks),
                    "source_urls": " | ".join(candidate.source_urls),
                }
            )
    return path


def write_industry_report_stub(news_items: list[NewsItem], output_dir: Path) -> Path | None:
    industry_news: dict[str, list[NewsItem]] = defaultdict(list)
    for item in news_items:
        for industry in item.sectors:
            industry_news[industry].append(item)
    if not industry_news:
        return None

    industry, related_news = max(industry_news.items(), key=lambda entry: len(entry[1]))
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{industry.replace(' ', '_')}_{datetime.now().date().isoformat()}.md"
    path.write_text(
        "\n".join(
            [
                f"# {industry} Industry Research Report",
                "",
                f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
                "",
                "## Executive Summary",
                f"The current news flow surfaced {industry} as a target industry/theme for follow-up research.",
                "",
                "## Latest News",
                *[f"- {item.title} - {item.source} - {item.url}" for item in related_news[:10]],
                "",
                "## Financial Analysis To Complete",
                "- Identify public companies with direct revenue exposure to this theme.",
                "- Compare revenue growth, margins, free cash flow, leverage, valuation multiples, and guidance revisions.",
                "",
                "## Pros",
                "- Industry theme was discovered from the current news cycle rather than a preselected ticker list.",
                "- Sector-level work can reveal better ticker candidates after entity validation.",
                "",
                "## Cons And Risks",
                "- Industry signal may not yet map to a high-confidence public ticker.",
                "- More primary-source financial validation is required before investment use.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_report_stub(candidate: StockCandidate, output_dir: Path) -> Path:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{candidate.symbol}_{datetime.now().date().isoformat()}.md"
    path.write_text(
        "\n".join(
            [
                f"# {candidate.symbol} Company Research Report",
                "",
                f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
                "",
                "## Executive Summary",
                candidate.thesis,
                "",
                "## Latest News And Catalysts",
                *[f"- {item}" for item in candidate.catalysts],
                "",
                "## Discovered Industry Theme",
                "- This company was selected because the current news cycle surfaced both a ticker and an industry/theme signal.",
                "",
                "## Financial Statement Review",
                "- Pull latest 10-K, 10-Q, earnings release, revenue growth, margins, cash flow, debt, and guidance before investment use.",
                "",
                "## Pros",
                "- News flow created an objective research trigger without using a preselected ticker list.",
                "- Multiple sources, industry keywords, and catalyst terms can increase signal quality.",
                "",
                "## Cons And Risks",
                *[f"- {item}" for item in candidate.risks],
                "- Ticker extraction from headlines can include false positives and must be validated.",
                "- Valuation, competitive position, and accounting quality are not yet validated.",
                "",
                "## Next Actions",
                "- Confirm ticker identity and company name from a trusted market data source.",
                "- Verify business impact from primary filings.",
                "- Compare valuation and operating metrics against industry peers.",
                "- Track whether news creates durable estimate revisions or only short-term sentiment.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def run_workflow(config_path: Path, mode: str) -> None:
    load_dotenv()
    config = load_config(config_path)
    output_dir = Path(config.get("reports", {}).get("output_dir", "outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    news_items = fetch_rss_news(config)
    digest_path = output_dir / f"news_digest_{datetime.now().date().isoformat()}.md"
    digest_path.write_text(build_digest(news_items, config), encoding="utf-8")

    candidates = score_candidates(news_items, config)
    watchlist_threshold = config.get("scoring", {}).get("thresholds", {}).get("watchlist_min_score", 45)
    report_threshold = config.get("scoring", {}).get("thresholds", {}).get("report_min_score", 65)
    watchlist_candidates = [candidate for candidate in candidates if candidate.score >= watchlist_threshold]
    watchlist_path = write_watchlist(watchlist_candidates, output_dir)
    industry_path = write_industry_themes(news_items, config, output_dir)

    report_path = None
    if mode in {"daily", "weekly"}:
        report_candidate = next((item for item in candidates if item.score >= report_threshold), None)
        report_path = write_report_stub(report_candidate, output_dir) if report_candidate else write_industry_report_stub(news_items, output_dir)

    print(f"Digest: {digest_path}")
    print(f"Industry themes: {industry_path}")
    print(f"Watchlist: {watchlist_path}")
    if report_path:
        print(f"Report: {report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Stockwatch financial news agent workflow.")
    parser.add_argument("--config", type=Path, required=True, help="Path to workflow YAML config.")
    parser.add_argument("--mode", choices=["pulse", "daily", "weekly"], default="daily")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_workflow(args.config, args.mode)
