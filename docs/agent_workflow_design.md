# Agent Workflow Design

## Goal

Build a repeatable workflow that continuously monitors real-time financial news, summarizes important developments, discovers target industries from the news cycle, extracts stock tickers from the same news flow, and produces company or industry reports grounded in filings and financial analysis.

## Agents

### 1. News Monitor Agent

Responsibilities:

- Read configured real-time or near-real-time finance news feeds.
- Deduplicate articles by title, URL, source, and timestamp.
- Detect mentioned tickers, industries, macro themes, competitors, and supply chain links.
- Label urgency: breaking, market open, earnings, regulatory, M&A, guidance, litigation, product, macro, analyst action.

### 2. Digest Agent

Responsibilities:

- Cluster related stories into themes.
- Produce Chinese and English summaries when needed.
- Preserve source URLs and publication timestamps.
- Separate facts, market interpretation, and unresolved uncertainty.

### 3. Industry Discovery Agent

Responsibilities:

- Rank industries and themes from the monitored news set.
- Use configurable industry keywords rather than a hardcoded stock watchlist.
- Identify whether a theme is company-specific, sector-wide, macro-driven, or regulatory.

### 4. Ticker Extraction And Candidate Scoring Agent

Responsibilities:

- Extract tickers from article titles and summaries.
- Score each ticker using only current news-derived signals.
- Combine mention count, source breadth, industry theme strength, catalyst strength, and recency.
- Produce watchlist candidates and high-score report candidates.

### 5. Filing And Financials Agent

Responsibilities:

- Retrieve SEC 10-K, 10-Q, 8-K, earnings releases, investor presentations, and guidance.
- Extract revenue growth, gross margin, operating margin, free cash flow, debt, share count, segment performance, and management outlook.
- Compare company metrics with industry peers.

### 6. Report Agent

Responsibilities:

- Generate a company or industry report.
- Include executive summary, discovered industry theme, recent news, financial statement analysis, valuation context, catalysts, risks, pros, cons, and watch actions.
- Clearly mark confidence level and missing evidence.

## Scoring Framework

Candidate score is a 0-100 research-ranking score, not a buy or sell signal. No ticker receives a score boost because it was manually preselected.

- Ticker news mentions: How often does the ticker appear in current monitored news?
- Source breadth: Is the signal present across multiple sources?
- Industry theme strength: Does the ticker connect to a currently active target industry/theme?
- Catalyst strength: Does the news include earnings, guidance, M&A, regulation, approval, contract, upgrade/downgrade, or other catalyst terms?
- Recency: Is the signal fresh enough to matter for monitoring?

## Report Quality Gates

Every generated report should answer:

- What changed?
- Which industries/themes were discovered from the news?
- Which tickers were extracted from the same news flow?
- Why might the change matter financially?
- What evidence supports the thesis?
- What are the biggest risks or counterarguments?
- What should be watched next?

## Recommended Automation

- Run pulse mode every 30 minutes during market hours.
- Run daily mode after US market close.
- Run weekly mode on Saturday to build deeper reports for top candidates.

## Future Production Enhancements

- Add trusted ticker/entity resolution to reduce false positives.
- Add paid market data providers for prices, fundamentals, estimates, and peer multiples.
- Add SEC company ticker mapping and XBRL extraction.
- Add vector storage for historical news and prior reports.
- Add alert delivery through email, Slack, Discord, or a dashboard.
- Add portfolio-aware risk limits and position sizing rules.

