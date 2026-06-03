from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
