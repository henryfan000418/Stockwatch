from __future__ import annotations

import json
from typing import Any

from stockwatch_workflow.models import FinancialReportSignal


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_FINANCIALS_PROMPT = """\
You are a financial analyst reviewing quarterly financial statements.

Ticker: {ticker}
Quarterly data (most recent first):
{quarterly_table}

Analyze these financial trends and return a JSON object with this exact structure:
{{
  "revenue_trend": "growing" | "flat" | "declining",
  "margin_trend": "expanding" | "stable" | "contracting",
  "fcf_trend": "improving" | "stable" | "deteriorating",
  "summary": "<one concise sentence summarizing the financial trajectory>",
  "key_metrics": {{
    "latest_quarterly_revenue": "<formatted string e.g. $12.5B>",
    "yoy_revenue_growth": "<e.g. +15.2%>",
    "net_profit_margin": "<e.g. 28.3%>",
    "operating_cash_flow": "<e.g. $8.2B>"
  }}
}}

Return only the JSON, no other text."""

_ANALYST_PROMPT = """\
You are interpreting Wall Street analyst consensus data for {ticker}.

Current price: {current_price}
Analyst price targets: mean={mean_target}, high={high_target}, low={low_target}
Rating breakdown: Strong Buy={strong_buy}, Buy={buy}, Hold={hold}, Sell={sell}, Strong Sell={strong_sell}
Total analysts: {total_analysts}
EPS estimate (current quarter): {eps_current_q}
EPS estimate (next quarter): {eps_next_q}
Revenue estimate trend: {rev_trend}

Return a JSON object with this exact structure:
{{
  "consensus": "strong_buy" | "buy" | "hold" | "underperform" | "sell",
  "avg_price_target": <number>,
  "upside_downside": "<e.g. +12.3% or -5.1%>",
  "analyst_count": <int>,
  "buy_count": <int>,
  "hold_count": <int>,
  "sell_count": <int>,
  "eps_estimate_trend": "raising" | "stable" | "cutting",
  "summary": "<one concise sentence on analyst sentiment>"
}}

Return only the JSON, no other text."""


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------

def run_financial_report_agent(
    ticker: str,
    llm_client: Any | None = None,
) -> FinancialReportSignal | None:
    """Fetch 1-year financials + analyst consensus via yfinance; optionally LLM-summarize."""
    try:
        import yfinance as yf  # type: ignore
    except ImportError:
        return None

    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception:
        return None

    if not info or info.get("quoteType") is None:
        return None

    quarterly_data = _extract_quarterly(t)
    financials_analysis = _analyze_financials(ticker, quarterly_data, llm_client, info)
    analyst_consensus = _analyze_analyst_consensus(ticker, t, info, llm_client)
    llm_summary = _build_combined_summary(financials_analysis, analyst_consensus, llm_client, ticker)

    return FinancialReportSignal(
        financials=financials_analysis,
        analyst_consensus=analyst_consensus,
        llm_summary=llm_summary,
        quarterly_data=quarterly_data,
    )


# ---------------------------------------------------------------------------
# Financial data extraction
# ---------------------------------------------------------------------------

def _extract_quarterly(t: Any) -> list[dict[str, Any]]:
    """Extract last 4 quarters of key financials into a list of dicts."""
    rows: list[dict[str, Any]] = []
    try:
        qf = t.quarterly_financials
        qcf = t.quarterly_cashflow
    except Exception:
        return rows

    if qf is None or qf.empty:
        return rows

    cols = list(qf.columns)[:4]  # 4 most recent quarters
    for col in cols:
        if hasattr(col, "strftime"):
            q_num = (col.month - 1) // 3 + 1
            period = f"{col.year}-Q{q_num}"
        else:
            period = str(col)[:10]
        try:
            revenue = _safe_val(qf, "Total Revenue", col)
            net_income = _safe_val(qf, "Net Income", col)
            gross_profit = _safe_val(qf, "Gross Profit", col)
            op_cf = None
            if qcf is not None and not qcf.empty and col in qcf.columns:
                op_cf = _safe_val(qcf, "Operating Cash Flow", col)

            net_margin = (net_income / revenue * 100) if revenue and net_income else None
            gross_margin = (gross_profit / revenue * 100) if revenue and gross_profit else None

            rows.append({
                "period": period,
                "revenue": _fmt_number(revenue),
                "revenue_raw": revenue,
                "net_income": _fmt_number(net_income),
                "net_margin": f"{net_margin:.1f}%" if net_margin is not None else "N/A",
                "gross_margin": f"{gross_margin:.1f}%" if gross_margin is not None else "N/A",
                "operating_cash_flow": _fmt_number(op_cf),
            })
        except Exception:
            continue
    return rows


def _safe_val(df: Any, row_name: str, col: Any) -> float | None:
    """Extract a single value from a DataFrame, returning None on failure."""
    import pandas as pd
    for name in df.index:
        if row_name.lower() in str(name).lower():
            try:
                val = df.loc[name, col]
                if pd.notna(val):
                    return float(val)
            except Exception:
                pass
    return None


def _fmt_number(val: float | None) -> str:
    if val is None:
        return "N/A"
    abs_val = abs(val)
    sign = "-" if val < 0 else ""
    if abs_val >= 1e9:
        return f"{sign}${abs_val/1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val/1e6:.1f}M"
    return f"{sign}${abs_val:,.0f}"


def _analyze_financials(
    ticker: str,
    quarterly_data: list[dict],
    llm_client: Any | None,
    info: dict,
) -> dict[str, Any]:
    if not quarterly_data:
        return {"error": "no_quarterly_data"}

    # Simple heuristic fallback (no LLM)
    result: dict[str, Any] = {
        "revenue_trend": _calc_trend([r["revenue_raw"] for r in quarterly_data if r.get("revenue_raw")]),
        "margin_trend": "stable",
        "fcf_trend": "stable",
        "summary": "Financial trend computed from quarterly data.",
        "key_metrics": {
            "latest_quarterly_revenue": quarterly_data[0]["revenue"] if quarterly_data else "N/A",
            "net_profit_margin": quarterly_data[0]["net_margin"] if quarterly_data else "N/A",
            "gross_margin": quarterly_data[0]["gross_margin"] if quarterly_data else "N/A",
            "operating_cash_flow": quarterly_data[0]["operating_cash_flow"] if quarterly_data else "N/A",
        },
    }

    if llm_client is None:
        return result

    table_lines = ["Period | Revenue | Net Income | Net Margin | Op. Cash Flow"]
    for q in quarterly_data:
        table_lines.append(
            f"{q['period']} | {q['revenue']} | {q['net_income']} | {q['net_margin']} | {q['operating_cash_flow']}"
        )

    prompt = _FINANCIALS_PROMPT.format(
        ticker=ticker,
        quarterly_table="\n".join(table_lines),
    )
    try:
        raw = _call_llm(llm_client, prompt, max_tokens=512)
        parsed = json.loads(raw)
        result.update(parsed)
    except Exception:
        pass
    return result


def _calc_trend(values: list[float | None]) -> str:
    clean = [v for v in values if v is not None]
    if len(clean) < 2:
        return "flat"
    if clean[0] > clean[-1] * 1.05:
        return "growing"
    if clean[0] < clean[-1] * 0.95:
        return "declining"
    return "flat"


# ---------------------------------------------------------------------------
# Analyst consensus extraction
# ---------------------------------------------------------------------------

def _analyze_analyst_consensus(
    ticker: str,
    t: Any,
    info: dict,
    llm_client: Any | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}

    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    # Price targets
    try:
        pt = t.analyst_price_targets
        mean_target = getattr(pt, "mean", None) if pt is not None else None
        high_target = getattr(pt, "high", None) if pt is not None else None
        low_target = getattr(pt, "low", None) if pt is not None else None
        current_pt = getattr(pt, "current", None) if pt is not None else None
        if current_pt and not current_price:
            current_price = current_pt
    except Exception:
        mean_target = high_target = low_target = None

    # Upside/downside
    upside_str = "N/A"
    if mean_target and current_price and current_price > 0:
        pct = (mean_target - current_price) / current_price * 100
        upside_str = f"{'+' if pct >= 0 else ''}{pct:.1f}%"

    # Rating breakdown from recommendations
    strong_buy = buy = hold = sell = strong_sell = 0
    try:
        recs = t.recommendations
        if recs is not None and not recs.empty:
            # Use most recent 3 months
            recent = recs.tail(20)
            for _, row in recent.iterrows():
                grade = str(row.get("To Grade", "")).lower()
                if "strong buy" in grade or grade == "outperform":
                    strong_buy += 1
                elif "buy" in grade or "overweight" in grade or "positive" in grade:
                    buy += 1
                elif "hold" in grade or "neutral" in grade or "market perform" in grade or "equal" in grade:
                    hold += 1
                elif "sell" in grade or "underperform" in grade or "underweight" in grade or "negative" in grade:
                    sell += 1
    except Exception:
        pass

    # EPS estimates
    eps_current_q = eps_next_q = "N/A"
    try:
        ee = t.earnings_estimate
        if ee is not None and not ee.empty:
            for col_name in ["0q", "+1q"]:
                if col_name in ee.columns:
                    val = ee.loc["avg", col_name] if "avg" in ee.index else None
                    if col_name == "0q":
                        eps_current_q = f"${val:.2f}" if val else "N/A"
                    else:
                        eps_next_q = f"${val:.2f}" if val else "N/A"
    except Exception:
        pass

    # Revenue estimate trend
    rev_trend = "N/A"
    try:
        re = t.revenue_estimate
        if re is not None and not re.empty:
            rev_trend = "available"
    except Exception:
        pass

    total_analysts = strong_buy + buy + hold + sell + strong_sell

    # Heuristic consensus
    bullish_count = strong_buy + buy
    bearish_count = sell + strong_sell
    if total_analysts == 0:
        consensus = "hold"
    elif bullish_count / total_analysts >= 0.6:
        consensus = "buy" if strong_buy < bullish_count / 2 else "strong_buy"
    elif bearish_count / total_analysts >= 0.4:
        consensus = "underperform"
    else:
        consensus = "hold"

    result = {
        "consensus": consensus,
        "avg_price_target": round(mean_target, 2) if mean_target else None,
        "high_price_target": round(high_target, 2) if high_target else None,
        "low_price_target": round(low_target, 2) if low_target else None,
        "current_price": round(current_price, 2) if current_price else None,
        "upside_downside": upside_str,
        "analyst_count": total_analysts,
        "strong_buy_count": strong_buy,
        "buy_count": buy,
        "hold_count": hold,
        "sell_count": sell + strong_sell,
        "eps_estimate_trend": "stable",
        "summary": f"{total_analysts} analysts tracked. Consensus: {consensus}. Target: {upside_str} upside.",
    }

    if llm_client is None or total_analysts == 0:
        return result

    prompt = _ANALYST_PROMPT.format(
        ticker=ticker,
        current_price=f"${current_price:.2f}" if current_price else "N/A",
        mean_target=f"${mean_target:.2f}" if mean_target else "N/A",
        high_target=f"${high_target:.2f}" if high_target else "N/A",
        low_target=f"${low_target:.2f}" if low_target else "N/A",
        strong_buy=strong_buy, buy=buy, hold=hold, sell=sell, strong_sell=strong_sell,
        total_analysts=total_analysts,
        eps_current_q=eps_current_q,
        eps_next_q=eps_next_q,
        rev_trend=rev_trend,
    )
    try:
        raw = _call_llm(llm_client, prompt, max_tokens=512)
        parsed = json.loads(raw)
        result.update(parsed)
    except Exception:
        pass

    return result


def _build_combined_summary(
    financials: dict,
    consensus: dict,
    llm_client: Any | None,
    ticker: str,
) -> str:
    fin_summary = financials.get("summary", "")
    analyst_summary = consensus.get("summary", "")
    if not fin_summary and not analyst_summary:
        return ""
    if llm_client is None:
        return f"{fin_summary} {analyst_summary}".strip()

    prompt = (
        f"In 2-3 sentences, write a professional summary combining these financial insights for {ticker}:\n"
        f"Financials: {fin_summary}\n"
        f"Analyst consensus: {analyst_summary}\n"
        "Be concise and factual."
    )
    try:
        return _call_llm(llm_client, prompt, max_tokens=256)
    except Exception:
        return f"{fin_summary} {analyst_summary}".strip()


# ---------------------------------------------------------------------------
# LLM dispatch
# ---------------------------------------------------------------------------

def _call_llm(client: Any, prompt: str, max_tokens: int = 512) -> str:
    client_type = type(client).__module__
    if "anthropic" in client_type:
        response = client.messages.create(
            model=getattr(client, "_model", "claude-haiku-4-5-20251001"),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    response = client.chat.completions.create(
        model=getattr(client, "_model", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content
