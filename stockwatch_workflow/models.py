from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    url: str
    published_at: datetime | None = None
    summary: str = ""
    tickers: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class StockCandidate:
    symbol: str
    company_name: str
    score: float
    thesis: str
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()


@dataclass
class CompanyReport:
    title: str
    symbol: str
    generated_at: datetime
    sections: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSignal:
    """Output from a single AI analyst agent."""
    signal: str  # "bullish" | "bearish" | "neutral"
    confidence: float  # 0-100
    reasoning: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinancialReportSignal:
    """Output from the financial report + analyst consensus agent."""
    financials: dict[str, Any] = field(default_factory=dict)
    analyst_consensus: dict[str, Any] = field(default_factory=dict)
    llm_summary: str = ""
    quarterly_data: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class EnrichedStockCandidate:
    """StockCandidate augmented with AI agent analysis."""
    base: StockCandidate
    sentiment: AgentSignal | None = None
    fundamentals: AgentSignal | None = None
    financial_report: FinancialReportSignal | None = None
    thesis: str = ""
    overall_confidence: float = 0.0
