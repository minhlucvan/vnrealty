---
name: re-risk
description: Portfolio and deal risk: concentration by ward and type, LTV, DSCR, liquidity months, rate and price shocks, vacancy shock, legal and zoning flags, each with the number behind it. Triggers on "rủi ro", "đòn bẩy", "risk", "stress test", "what if rates rise".
when_to_use: Risk review and stress testing.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-risk

1. Run `risk --cash <liquid cash> --json`.
2. Rank the flags by how close each is to a forced sale: liquidity < 6 months, DSCR < 1.2 after a +3 pt rate shock,
   LTV over the limit after −30% prices.
3. For each flag, give the cheapest fix (pay down, refinance, raise rent, hold more cash, sell the weakest unit).
   Quantify each fix by re-running with the changed input.
