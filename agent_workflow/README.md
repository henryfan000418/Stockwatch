# Stockwatch Agent Workflow

This workflow monitors financial news, summarizes market-moving events, discovers target industries from the news cycle, extracts mentioned stock tickers, and generates company or industry research reports.

It is designed as a first production-friendly skeleton: sources, industry keyword maps, catalyst keywords, scoring rules, and report templates live in configuration files, while the Python runner orchestrates each agent step.

## Workflow Stages

1. News monitor: collect real-time or recent finance headlines from configured sources.
2. News digest: summarize key facts, identify target industries/themes, and extract mentioned tickers from news text.
3. Theme discovery: rank industries by current news concentration and catalyst keywords.
4. Candidate discovery: rank stocks or ETFs only when they appear in the monitored news flow.
5. Filing review: pull 10-K, 10-Q, earnings releases, and industry data for selected companies.
6. Report generation: produce a company or industry report with thesis, catalysts, financials, risks, pros, cons, and next actions.

## Quick Start

`powershell
cd C:\Users\herry\Desktop\codex\stockwatch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m stockwatch_workflow.run --config config/workflow.example.yaml --mode daily
```

## Suggested Schedule

- Market open pulse: every 30 minutes during US market hours.
- Daily digest: after US market close.
- Weekly research: every weekend for top ranked news-discovered candidates.

## Output

Generated files are written to `outputs/`:

- `news_digest_YYYY-MM-DD.md`
- `industry_themes_YYYY-MM-DD.csv`
- `watchlist_YYYY-MM-DD.csv`
- `reports/{ticker_or_industry}_YYYY-MM-DD.md`

## Discovery Rule

The workflow does not use a preselected ticker list. It first scans current news, discovers the strongest industries/themes, then extracts tickers directly from article titles and summaries. Any candidate must be validated against trusted market data and primary filings before investment use.

## Investment Disclaimer

This workflow is for research assistance only. It does not provide personalized financial advice, and every output should be verified against primary filings and market data before any investment decision.

