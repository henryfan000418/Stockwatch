from __future__ import annotations

from typing import Any

from stockwatch_workflow.models import AgentSignal


def run_fundamentals_agent(ticker: str, config: dict[str, Any] | None = None) -> AgentSignal | None:
    """
    Analyze fundamental metrics for a ticker using yfinance (free, no API key needed).
    Adapted from ai-hedge-fund fundamentals.py — same 4-dimension scoring logic.
    """
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return None

    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return None

    if not info or info.get("quoteType") is None:
        return None

    signals: list[str] = []
    reasoning: dict[str, Any] = {}

    # 1. Profitability
    roe = info.get("returnOnEquity")
    net_margin = info.get("profitMargins")
    op_margin = info.get("operatingMargins")

    profit_score = sum([
        roe is not None and roe > 0.15,
        net_margin is not None and net_margin > 0.20,
        op_margin is not None and op_margin > 0.15,
    ])
    profit_signal = "bullish" if profit_score >= 2 else "bearish" if profit_score == 0 else "neutral"
    signals.append(profit_signal)
    reasoning["profitability"] = {
        "signal": profit_signal,
        "roe": f"{roe:.2%}" if roe is not None else "N/A",
        "net_margin": f"{net_margin:.2%}" if net_margin is not None else "N/A",
        "op_margin": f"{op_margin:.2%}" if op_margin is not None else "N/A",
    }

    # 2. Growth
    rev_growth = info.get("revenueGrowth")
    earn_growth = info.get("earningsGrowth")
    book_val = info.get("bookValue")

    growth_score = sum([
        rev_growth is not None and rev_growth > 0.10,
        earn_growth is not None and earn_growth > 0.10,
    ])
    growth_signal = "bullish" if growth_score >= 2 else "bearish" if growth_score == 0 else "neutral"
    signals.append(growth_signal)
    reasoning["growth"] = {
        "signal": growth_signal,
        "revenue_growth": f"{rev_growth:.2%}" if rev_growth is not None else "N/A",
        "earnings_growth": f"{earn_growth:.2%}" if earn_growth is not None else "N/A",
    }

    # 3. Financial Health
    current_ratio = info.get("currentRatio")
    debt_to_equity = info.get("debtToEquity")
    free_cash_flow = info.get("freeCashflow")
    net_income = info.get("netIncomeToCommon")

    health_score = sum([
        current_ratio is not None and current_ratio > 1.5,
        debt_to_equity is not None and debt_to_equity < 50,  # yfinance gives % form
        free_cash_flow is not None and net_income is not None and net_income != 0
        and (free_cash_flow / net_income) > 0.8,
    ])
    health_signal = "bullish" if health_score >= 2 else "bearish" if health_score == 0 else "neutral"
    signals.append(health_signal)
    reasoning["financial_health"] = {
        "signal": health_signal,
        "current_ratio": f"{current_ratio:.2f}" if current_ratio is not None else "N/A",
        "debt_to_equity": f"{debt_to_equity:.1f}" if debt_to_equity is not None else "N/A",
    }

    # 4. Valuation
    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    ps = info.get("priceToSalesTrailing12Months")

    overvalued = sum([
        pe is not None and pe > 25,
        pb is not None and pb > 3,
        ps is not None and ps > 5,
    ])
    val_signal = "bearish" if overvalued >= 2 else "bullish" if overvalued == 0 else "neutral"
    signals.append(val_signal)
    reasoning["valuation"] = {
        "signal": val_signal,
        "pe": f"{pe:.2f}" if pe is not None else "N/A",
        "pb": f"{pb:.2f}" if pb is not None else "N/A",
        "ps": f"{ps:.2f}" if ps is not None else "N/A",
    }

    bullish = signals.count("bullish")
    bearish = signals.count("bearish")
    overall = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    confidence = round(max(bullish, bearish) / len(signals) * 100, 1)

    return AgentSignal(signal=overall, confidence=confidence, reasoning=reasoning)
