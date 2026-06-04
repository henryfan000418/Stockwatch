from __future__ import annotations

import argparse
import csv
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from stockwatch_workflow.models import (
    NewsItem,
    StockCandidate,
    AgentSignal,
    EnrichedStockCandidate,
)
from stockwatch_workflow.news import fetch_rss_news, fetch_newsapi_news, fetch_reddit_news
from stockwatch_workflow.news.rss_fetcher import extract_tickers, extract_industries


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


# ---------------------------------------------------------------------------
# News aggregation
# ---------------------------------------------------------------------------

def fetch_all_news(config: dict[str, Any]) -> list[NewsItem]:
    items: list[NewsItem] = []
    items.extend(fetch_rss_news(config))
    items.extend(fetch_newsapi_news(config))
    items.extend(fetch_reddit_news(config))
    return _deduplicate(items)


def _deduplicate(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        key = item.url or item.title
        if key and key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# Digest and scoring
# ---------------------------------------------------------------------------

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
    lines.extend(_format_counter(industry_counts))
    lines.extend(["", "## Extracted Stock Tickers", ""])
    lines.extend(_format_counter(ticker_counts))
    lines.extend(["", "## Catalyst Keywords", ""])
    lines.extend(_format_counter(catalyst_counts))
    lines.extend(["", "## Top Headlines", ""])

    for item in news_items[:20]:
        tickers = f" [{', '.join(item.tickers)}]" if item.tickers else ""
        industries = f" ({', '.join(item.sectors)})" if item.sectors else ""
        lines.append(f"- {item.title}{tickers}{industries} - {item.source} - {item.url}")

    return "\n".join(lines) + "\n"


def _format_counter(counter: Counter[str]) -> list[str]:
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
        recency_score = _score_recency(related_news)
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

    return sorted(candidates, key=lambda c: c.score, reverse=True)


def _score_recency(news_items: list[NewsItem]) -> int:
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


# ---------------------------------------------------------------------------
# AI Agent pipeline
# ---------------------------------------------------------------------------

def _build_llm_client(config: dict[str, Any]) -> Any | None:
    agent_cfg = config.get("agents", {})
    provider = agent_cfg.get("llm_provider", "anthropic")
    model = agent_cfg.get("model", "claude-haiku-4-5-20251001")

    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        try:
            import anthropic  # type: ignore
            client = anthropic.Anthropic(api_key=api_key)
            client._model = model
            return client
        except ImportError:
            return None

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            return None
        try:
            import openai  # type: ignore
            client = openai.OpenAI(api_key=api_key)
            client._model = model
            return client
        except ImportError:
            return None

    return None


def run_agent_pipeline(
    candidates: list[StockCandidate],
    news_items: list[NewsItem],
    config: dict[str, Any],
) -> list[EnrichedStockCandidate]:
    agent_cfg = config.get("agents", {})
    if not agent_cfg.get("enabled", False):
        return []

    llm_client = _build_llm_client(config)
    if llm_client is None:
        print("Warning: agents.enabled=true but no valid LLM API key found. Skipping agent pipeline.")
        return []

    from stockwatch_workflow.agents import (
        run_sentiment_agent,
        run_fundamentals_agent,
        run_thesis_agent,
    )

    max_analyze = agent_cfg.get("max_candidates_to_analyze", 10)
    run_sentiment = agent_cfg.get("run_sentiment", True)
    run_fund = agent_cfg.get("run_fundamentals", True)
    run_thesis = agent_cfg.get("run_thesis", True)

    enriched: list[EnrichedStockCandidate] = []
    for candidate in candidates[:max_analyze]:
        print(f"  [agents] Analyzing {candidate.symbol}...")

        sentiment: AgentSignal | None = None
        if run_sentiment:
            sentiment = run_sentiment_agent(candidate.symbol, news_items, llm_client)

        fundamentals: AgentSignal | None = None
        if run_fund:
            fundamentals = run_fundamentals_agent(candidate.symbol, config)

        thesis = ""
        if run_thesis and llm_client:
            thesis = run_thesis_agent(candidate, sentiment, fundamentals, llm_client)

        scores = [s.confidence for s in [sentiment, fundamentals] if s is not None]
        overall_conf = round(sum(scores) / len(scores), 1) if scores else 0.0

        enriched.append(
            EnrichedStockCandidate(
                base=candidate,
                sentiment=sentiment,
                fundamentals=fundamentals,
                thesis=thesis,
                overall_confidence=overall_conf,
            )
        )

    return enriched


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_industry_themes(news_items: list[NewsItem], config: dict[str, Any], output_dir: Path) -> Path:
    path = output_dir / f"industry_themes_{datetime.now().date().isoformat()}.csv"
    industry_news: dict[str, list[NewsItem]] = defaultdict(list)
    for item in news_items:
        for industry in item.sectors:
            industry_news[industry].append(item)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["industry", "article_count", "catalysts", "top_headlines", "source_urls"])
        writer.writeheader()
        for industry, related_news in sorted(industry_news.items(), key=lambda e: len(e[1]), reverse=True):
            related_text = " ".join(f"{item.title} {item.summary}" for item in related_news)
            writer.writerow({
                "industry": industry,
                "article_count": len(related_news),
                "catalysts": " | ".join(extract_catalysts(related_text, config)),
                "top_headlines": " | ".join(item.title for item in related_news[:5]),
                "source_urls": " | ".join(item.url for item in related_news[:5] if item.url),
            })
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
            writer.writerow({
                "symbol": candidate.symbol,
                "company_name": candidate.company_name,
                "score": candidate.score,
                "thesis": candidate.thesis,
                "catalysts": " | ".join(candidate.catalysts),
                "risks": " | ".join(candidate.risks),
                "source_urls": " | ".join(candidate.source_urls),
            })
    return path


def write_enriched_report(enriched: EnrichedStockCandidate, output_dir: Path) -> Path:
    """Write an AI-generated research report for an enriched candidate."""
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    symbol = enriched.base.symbol
    path = reports_dir / f"{symbol}_{datetime.now().date().isoformat()}.md"

    sentiment_section = ""
    if enriched.sentiment:
        s = enriched.sentiment
        sentiment_section = (
            f"## Sentiment Analysis\n\n"
            f"- Signal: **{s.signal.upper()}** (confidence: {s.confidence:.0f}%)\n"
            f"- Themes: {', '.join(s.reasoning.get('key_themes', []))}\n"
            f"- Summary: {s.reasoning.get('summary', '')}\n"
        )

    fundamentals_section = ""
    if enriched.fundamentals:
        f = enriched.fundamentals
        r = f.reasoning
        fundamentals_section = (
            f"## Fundamental Analysis\n\n"
            f"- Signal: **{f.signal.upper()}** (confidence: {f.confidence:.0f}%)\n"
            f"- Profitability: {r.get('profitability', {})}\n"
            f"- Growth: {r.get('growth', {})}\n"
            f"- Financial Health: {r.get('financial_health', {})}\n"
            f"- Valuation: {r.get('valuation', {})}\n"
        )

    thesis_section = enriched.thesis or (
        f"## Investment Thesis\n\n{enriched.base.thesis}\n\n"
        f"## Risks\n\n" + "\n".join(f"- {r}" for r in enriched.base.risks)
    )

    path.write_text(
        "\n".join([
            f"# {symbol} Research Report",
            "",
            f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
            f"Heuristic Score: {enriched.base.score:.1f}/100 | AI Confidence: {enriched.overall_confidence:.0f}%",
            "",
            "## Source URLs",
            *[f"- {u}" for u in enriched.base.source_urls],
            "",
            sentiment_section,
            fundamentals_section,
            thesis_section,
        ]),
        encoding="utf-8",
    )
    return path


def write_report_stub(candidate: StockCandidate, output_dir: Path) -> Path:
    """Fallback static report when AI agents are not enabled."""
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{candidate.symbol}_{datetime.now().date().isoformat()}.md"
    path.write_text(
        "\n".join([
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
            "## Financial Statement Review",
            "- Pull latest 10-K, 10-Q, earnings release, revenue growth, margins, cash flow, debt, and guidance before investment use.",
            "",
            "## Pros",
            "- News flow created an objective research trigger without using a preselected ticker list.",
            "",
            "## Cons And Risks",
            *[f"- {item}" for item in candidate.risks],
            "- Ticker extraction from headlines can include false positives and must be validated.",
            "",
            "## Next Actions",
            "- Confirm ticker identity and company name from a trusted market data source.",
            "- Verify business impact from primary filings.",
            "- Compare valuation and operating metrics against industry peers.",
        ]) + "\n",
        encoding="utf-8",
    )
    return path


def write_industry_report_stub(news_items: list[NewsItem], output_dir: Path) -> Path | None:
    industry_news: dict[str, list[NewsItem]] = defaultdict(list)
    for item in news_items:
        for industry in item.sectors:
            industry_news[industry].append(item)
    if not industry_news:
        return None

    industry, related_news = max(industry_news.items(), key=lambda e: len(e[1]))
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{industry.replace(' ', '_')}_{datetime.now().date().isoformat()}.md"
    path.write_text(
        "\n".join([
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
        ]) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_workflow(config_path: Path, mode: str) -> None:
    load_dotenv()
    config = load_config(config_path)
    output_dir = Path(config.get("reports", {}).get("output_dir", "outputs"))
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching news...")
    news_items = fetch_all_news(config)
    print(f"  {len(news_items)} articles collected.")

    digest_path = output_dir / f"news_digest_{datetime.now().date().isoformat()}.md"
    digest_path.write_text(build_digest(news_items, config), encoding="utf-8")

    candidates = score_candidates(news_items, config)
    watchlist_threshold = config.get("scoring", {}).get("thresholds", {}).get("watchlist_min_score", 45)
    report_threshold = config.get("scoring", {}).get("thresholds", {}).get("report_min_score", 65)
    watchlist_candidates = [c for c in candidates if c.score >= watchlist_threshold]
    watchlist_path = write_watchlist(watchlist_candidates, output_dir)
    industry_path = write_industry_themes(news_items, config, output_dir)

    enriched_candidates = run_agent_pipeline(candidates, news_items, config)

    report_path = None
    if mode in {"daily", "weekly"}:
        if enriched_candidates:
            report_path = write_enriched_report(enriched_candidates[0], output_dir)
        else:
            report_candidate = next((c for c in candidates if c.score >= report_threshold), None)
            report_path = (
                write_report_stub(report_candidate, output_dir)
                if report_candidate
                else write_industry_report_stub(news_items, output_dir)
            )

    print(f"Digest:          {digest_path}")
    print(f"Industry themes: {industry_path}")
    print(f"Watchlist:       {watchlist_path}")
    if report_path:
        print(f"Report:          {report_path}")
    if enriched_candidates:
        print(f"AI-analyzed:     {len(enriched_candidates)} candidates")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Stockwatch financial news agent workflow.")
    parser.add_argument("--config", type=Path, required=True, help="Path to workflow YAML config.")
    parser.add_argument("--mode", choices=["pulse", "daily", "weekly"], default="daily")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_workflow(args.config, args.mode)
