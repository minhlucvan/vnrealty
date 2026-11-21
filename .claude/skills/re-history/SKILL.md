---
name: re-history
description: Reconstruct the price history of a lot, listing or ward: dated facts (purchases, sales, past listings of the same property) linked by the ward/city index, with bands that widen away from each fact. Triggers on "lịch sử giá", "giá trước đây", "price history", "how did it get here".
when_to_use: Understanding past prices when only a few facts exist.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-history

1. Collect the anchors:
   - the listing's own observations (`history <listing> --json`);
   - known sales (`sale list --json`);
   - the user's purchase (unit.cost and bought_at);
   - archived listings found through WebSearch (the old URL, date and price).

   Every anchor is labelled fact or estimate, with its source.
2. Run `history <subject> --index <ward|city> --json`. It returns a yearly value with lo/hi and a label of fact or
   reconstructed.
3. Narrate the path against the Đà Nẵng cycle (the 2018 boom, 2019 curbs, COVID, the 2022 peak, the 2023 credit
   slump, the 2024–26 run). Cite the news for each phase. Make clear that only the anchors are facts.
