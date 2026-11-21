---
name: re-learn
description: Grade past estimates and decisions: valuation MAPE, bias and band coverage per method, paper-deal outcomes, earned method weights, and written lessons. Triggers on "đánh giá lại", "học được gì", "calibrate", "how accurate", "lessons".
when_to_use: Monthly, or after new sale evidence arrives.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-learn

1. Run `calibrate --as-of <date> --json` (per-method MAPE, bias, coverage, n, and the new weights) and
   `ledger scorecard --json`.
2. Interpret: bias means the asking→sale haircut is off, so propose a new value with its evidence. Low coverage means
   the bands are too narrow.
3. Append the lessons to `data/LESSONS.md` with dates and numbers.
