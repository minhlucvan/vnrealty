---
name: re-forecast
description: Build and use the price model for the future — mine published price-history charts, fit and backtest area index models (drift, local trend, mean-reverting growth, driver regression), blend them by out-of-sample error, and project an asset's price (p10/p50/p90 by year) from today's estimate × the area fan × local catalysts, with sell timing. Triggers on "dự báo giá", "mô hình giá", "giá tương lai", "price model", "forecast", "projection", "backtest".
when_to_use: Any forward price question once today's value is known; or to extend and grade the price history. Use re-project for a quick scenario view without fitted models.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__javascript_tool, mcp__claude-in-chrome__get_page_text, mcp__claude-in-chrome__tabs_create_mcp, mcp__claude-in-chrome__tabs_context_mcp
---

# re-forecast — the price model

1. **History first.** Run `python3 -m vnrealty.cli series list --json` to see which areas and types have how many
   months, and from which sources. A model needs at least 24 months to backtest, so extend thin series:
   - In Chrome, open the area's price-history chart on batdongsan (area price trend pages) or guland (prices by
     street). Inject `browser script pricehistory` and save the capture with `capture save`, then run
     `series ingest`.
   - Add research-house quarterly figures (DKRA, Savills, CBRE Đà Nẵng reports) found through WebSearch:
     `series add <source> <scope> <ptype> --points '[["2025-03", 72e6], …]' --url …`.
   - Our own indices (`market index --save`) extend the series month by month from our own captures.

   Sources are chain-linked only where they overlap, and the overlap length is reported.
2. **Fit and backtest.** Run `forecast series <scope> <ptype> --json`. It gives each model's walk-forward error at
   3, 6, 12 and 24 months, the ensemble weights, and the fan (p10/p50/p90). If history is too short, the command
   says how many months are missing. Relay that; do not substitute a guess.
3. **Asset.** Run `forecast asset <listing|unit> --years 5 --json`. It combines today's triangulated value (with its
   band), the area fan, and only the *local* catalysts (those affecting this asset more than the area average;
   everything else is already in the index). It returns yearly p10/p50/p90 and sell timing (take-home after the 2%
   PIT and fees vs selling now and keeping the money on deposit).
4. **Explain** the result in this order:
   - which models carry weight and how good they were out of sample;
   - what the base path rests on;
   - how wide the fan is and why;
   - which local catalysts were added, with their chance and citation.

   An 80% band that past forecasts covered only 50% of the time is reported as too narrow.
5. **Record and grade.** Forecasts are stored automatically. Run `forecast grade --json` (or `re-learn`) monthly.
   Ensemble weights shift toward whichever model has actually been right.
