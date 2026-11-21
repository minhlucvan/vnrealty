---
name: re-plan
description: Find the best use of a property the investor owns: keep idle, lease bare land, build studios, shop plus studios, serviced apartments (CHDV), homestay, joint venture, or sell (to deposit or into a rental), with break-even rents and sell timing. Triggers on "nên làm gì với lô đất", "xây hay bán", "best plan", "what to do with my land".
when_to_use: Owned-property strategy decisions.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-plan

1. Build the Lot (value from `value unit:<id>`, area, buildable ratio and floors allowed by the zoning check, build
   cost from the reference table, rents from `market rents`).
2. Run `plan <lot.json> --json`. It returns each option's money in, net cash a month, yield, IRR, the break-even rent
   for the hurdle, and a ranked recommendation with reasons.
3. Add `project <unit>` for sell timing. Constraints the numbers do not see: co-owner consent, a loan due, a planning
   red flag. Name them.
4. Run `report plan <unit>`.
