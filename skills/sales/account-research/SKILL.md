---
name: account-research
description: Research companies and build detailed account profiles including revenue, business segments, competitive positioning, and recent news. Use when asked to research a company, analyze competitive position, find financial data, or create account profiles.
---

# Account Research

Research a target company and produce a structured account profile.

## Process

1. **Identify the target** -- extract company name, ticker, and region from the task context
2. **Research fundamentals** -- use web search to gather:
   - Latest revenue and financial highlights
   - Key business segments and their contributions
   - Recent news (last 6 months) -- earnings, partnerships, regulatory, M&A
   - Competitive landscape and market position
3. **Synthesize findings** into two output files

## Output Format

### `company_profile.md`

Narrative profile with these sections:
- **Overview** -- what the company does, where it operates, founding date
- **Financials** -- latest revenue, growth rate, profitability metrics
- **Business Segments** -- each segment with description and revenue contribution
- **Recent News** -- 3-5 most significant recent developments
- **Competitive Position** -- key competitors, market share, differentiation

### `company_data.json`

Structured data:
```json
{
  "name": "Company Name",
  "ticker": "TICK",
  "sector": "...",
  "region": "...",
  "revenue_usd": "...",
  "revenue_growth_pct": "...",
  "segments": [{"name": "...", "revenue_pct": "..."}],
  "competitors": ["..."],
  "recent_news": [{"date": "...", "headline": "...", "summary": "..."}]
}
```

## Quality Checks

- All financial figures must cite a source (earnings report, SEC filing, news article)
- Revenue figures should be the most recent available (quarterly or annual)
- Competitor list should include at least 3 direct competitors
