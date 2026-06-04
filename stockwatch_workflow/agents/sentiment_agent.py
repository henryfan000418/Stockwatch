from __future__ import annotations

import json
from typing import Any

from stockwatch_workflow.models import AgentSignal, NewsItem


_SENTIMENT_PROMPT = """\
You are a financial news sentiment analyst.

Below are news headlines and summaries related to the stock ticker {ticker}.
Analyze the overall market sentiment for this ticker based on these articles.

Articles:
{articles}

Return a JSON object with this exact structure:
{{
  "signal": "bullish" | "bearish" | "neutral",
  "confidence": <integer 0-100>,
  "reasoning": {{
    "bullish_count": <int>,
    "bearish_count": <int>,
    "neutral_count": <int>,
    "key_themes": [<string>, ...],
    "summary": "<one sentence>"
  }}
}}

Return only the JSON, no other text."""


def run_sentiment_agent(
    ticker: str,
    news_items: list[NewsItem],
    llm_client: Any,
) -> AgentSignal | None:
    """Analyze news sentiment for a ticker using an LLM. Returns None if no relevant news."""
    related = [
        item for item in news_items
        if ticker in item.tickers or ticker.lower() in item.title.lower()
    ]
    if not related:
        return None

    article_lines = []
    for i, item in enumerate(related[:20], 1):
        article_lines.append(f"{i}. [{item.source}] {item.title} — {item.summary[:200]}")

    prompt = _SENTIMENT_PROMPT.format(
        ticker=ticker,
        articles="\n".join(article_lines),
    )

    try:
        raw = _call_llm(llm_client, prompt)
        data = json.loads(raw)
        return AgentSignal(
            signal=data.get("signal", "neutral"),
            confidence=float(data.get("confidence", 50)),
            reasoning=data.get("reasoning", {}),
        )
    except Exception:
        return AgentSignal(signal="neutral", confidence=0.0, reasoning={"error": "parse_failed"})


def _call_llm(client: Any, prompt: str) -> str:
    """Dispatch to Anthropic or OpenAI client based on type."""
    client_type = type(client).__module__

    if "anthropic" in client_type:
        response = client.messages.create(
            model=getattr(client, "_model", "claude-haiku-4-5-20251001"),
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    # OpenAI-compatible
    response = client.chat.completions.create(
        model=getattr(client, "_model", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
    )
    return response.choices[0].message.content
