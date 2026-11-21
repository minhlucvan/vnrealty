---
name: re-project
description: Project a property's price forward: market drift × catalysts (bear/base/bull), Monte Carlo bands, the probability of beating a deposit or hurdle, and the best year to sell versus selling now. Triggers on "dự báo giá", "nên bán lúc nào", "giá sau 5 năm", "projection", "forecast", "hold or sell".
when_to_use: Forward price questions and sell-timing.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-project

1. Start from today's triangulated value (`value <subject> --json`) and the catalysts near it
   (`infra catalysts <subject> --km 3 --json`).
2. Run `project <subject> --years 5 --json`. It returns:
   - bear/base/bull paths and each catalyst's contribution;
   - Monte Carlo p10/p50/p90;
   - P(beat the deposit rate);
   - hold-vs-sell take-home by year (after the 2% PIT and fees) and the best year.
3. Explain what the base case rests on (which catalysts, at what chance) and what kills it. An empty lot pays
   nothing while you wait, so holding wins only if the lot grows faster than the deposit rate.
