---
name: re-compare
description: Compare several listings, units or options side by side on one basis: price/m², value gap, yield, IRR, DSCR, risk flags, legal status. Triggers on "so sánh", "căn nào tốt hơn", "compare", "which is better".
when_to_use: Choosing between two or more candidates.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-compare

1. Resolve each candidate to a subject. Run `value` on each so the value gap uses the same method.
2. Run `compare <id> <id> … --deal <template.json> --json`. Without a deal template there is no IRR or DSCR. It returns a normalised table (price, price/m², value gap, gross yield, yield on
   cost, cash-on-cash, DSCR, IRR, NPV, break-even occupancy, legal, flags) and a rank per metric.
3. Recommend based on the user's goal (yield vs growth vs safety). Show where the ranking flips, e.g. "B wins on
   yield, A on value gap; A only if the alley is car-wide".
4. Offer `report compare`.
