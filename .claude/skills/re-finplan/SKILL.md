---
name: re-finplan
description: Personal real-estate capital plan: affordability (debt-to-income, LTV and DSCR limits, reserve), the binding constraint, max price, and a purchase ladder that scales one deal into a portfolio over time. Triggers on "đủ tiền mua không", "vay được bao nhiêu", "kế hoạch tài chính", "afford", "financing", "scale the business".
when_to_use: Capacity and growth planning.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-finplan

1. The household inputs (cash, income, spending, existing debt payments, emergency months) live in
   `data/portfolio/household.json` (private). Ask once and save them.
2. Run `finplan --json` for affordability and the binding constraint. Run `finplan ladder <deal.json> --years 15
   --json` for the purchase ladder (units over time, cash flow, LTV, net worth, the target month).
3. Explain which constraint binds (cash, DTI, DSCR or the LTV cap) and the levers ranked by effect (savings rate,
   rent achieved, leverage, refinancing).
