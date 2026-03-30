---
name: audit-support
description: Perform financial health assessments and due diligence audits on companies. Use when asked to audit financials, assess financial health, evaluate creditworthiness, or score a company's financial position.
---

# Audit Support

Conduct a structured financial health assessment of a target company.

## Process

1. **Gather inputs** -- read any prior-step company profiles, financial data, or research
2. **Analyze financial health** across four dimensions:
   - **Revenue Growth** -- YoY trends, acceleration/deceleration, segment drivers
   - **Profitability** -- gross margin, operating margin, net margin, trajectory
   - **Balance Sheet Strength** -- debt-to-equity, current ratio, cash reserves
   - **Cash Generation** -- operating cash flow, free cash flow, cash conversion
3. **Score each dimension** on a 1-10 scale with justification
4. **Identify risks and flags** -- red flags, watch items, positive signals
5. **Produce output files**

## Scoring Guide

| Score | Meaning |
|-------|---------|
| 9-10 | Excellent -- top quartile performance, strong trajectory |
| 7-8 | Good -- above average, minor concerns only |
| 5-6 | Average -- in line with peers, some areas need attention |
| 3-4 | Below average -- material concerns, declining trajectory |
| 1-2 | Poor -- significant financial stress or deterioration |

## Output Format

### `financial_audit.md`

Narrative audit report with:
- **Executive Summary** -- 2-3 sentence overall assessment
- **Revenue Analysis** -- trends, drivers, risks
- **Profitability Analysis** -- margin analysis, peer comparison
- **Balance Sheet Review** -- leverage, liquidity, capital structure
- **Cash Flow Assessment** -- generation, usage, sustainability
- **Risk Factors** -- top 3-5 financial risks
- **Conclusion** -- overall financial health verdict

### `scorecard.json`

```json
{
  "company": "...",
  "assessment_date": "...",
  "scores": {
    "revenue_growth": {"score": 7, "rationale": "..."},
    "profitability": {"score": 6, "rationale": "..."},
    "balance_sheet": {"score": 8, "rationale": "..."},
    "cash_generation": {"score": 7, "rationale": "..."}
  },
  "overall_score": 7.0,
  "risk_flags": ["..."],
  "positive_signals": ["..."]
}
```
