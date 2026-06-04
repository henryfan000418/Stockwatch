from __future__ import annotations

import json
from typing import Any

from stockwatch_workflow.models import AgentSignal, StockCandidate


_THESIS_PROMPT = """\
You are a senior equity research analyst writing a concise investment research note.

Stock: {symbol}
News-based score: {score}/100
Catalyst headlines: {catalysts}

Sentiment Analysis: signal={sentiment_signal}, confidence={sentiment_conf}%
Key themes: {sentiment_themes}

Fundamentals Analysis: signal={fund_signal}, confidence={fund_conf}%
Profitability: {profitability}
Growth: {growth}
Valuation: {valuation}

Write a structured investment thesis in markdown with these exact sections:
## Investment Thesis
(2-3 sentences core logic)

## Bull Case
- Point 1
- Point 2
- Point 3

## Bear Case / Risks
- Risk 1
- Risk 2
- Risk 3

## Recommendation
One of: **WATCH** (monitor closely), **RESEARCH** (deep dive warranted), **SKIP** (insufficient signal)
One sentence explaining why.

Be concise and factual. Do not invent financial data not provided above."""


def run_thesis_agent(
    candidate: StockCandidate,
    sentiment: AgentSignal | None,
    fundamentals: AgentSignal | None,
    llm_client: Any,
) -> str:
    """Generate an AI investment thesis combining news scoring, sentiment, and fundamentals."""
    sentiment_signal = sentiment.signal if sentiment else "N/A"
    sentiment_conf = f"{sentiment.confidence:.0f}" if sentiment else "N/A"
    sentiment_themes = (
        ", ".join(sentiment.reasoning.get("key_themes", [])) if sentiment else "N/A"
    )

    fund_signal = fundamentals.signal if fundamentals else "N/A"
    fund_conf = f"{fundamentals.confidence:.0f}" if fundamentals else "N/A"
    profitability = (
        str(fundamentals.reasoning.get("profitability", {})) if fundamentals else "N/A"
    )
    growth = str(fundamentals.reasoning.get("growth", {})) if fundamentals else "N/A"
    valuation = str(fundamentals.reasoning.get("valuation", {})) if fundamentals else "N/A"

    prompt = _THESIS_PROMPT.format(
        symbol=candidate.symbol,
        score=candidate.score,
        catalysts="; ".join(candidate.catalysts[:5]),
        sentiment_signal=sentiment_signal,
        sentiment_conf=sentiment_conf,
        sentiment_themes=sentiment_themes,
        fund_signal=fund_signal,
        fund_conf=fund_conf,
        profitability=profitability,
        growth=growth,
        valuation=valuation,
    )

    try:
        return _call_llm(llm_client, prompt)
    except Exception as exc:
        return f"## Investment Thesis\n\nThesis generation failed: {exc}\n"


def _call_llm(client: Any, prompt: str) -> str:
    client_type = type(client).__module__

    if "anthropic" in client_type:
        response = client.messages.create(
            model=getattr(client, "_model", "claude-haiku-4-5-20251001"),
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    response = client.chat.completions.create(
        model=getattr(client, "_model", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    return response.choices[0].message.content
