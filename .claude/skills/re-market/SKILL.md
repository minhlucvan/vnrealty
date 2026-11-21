---
name: re-market
description: Read the Đà Nẵng market or one ward: asking price per m² by type and month, repeat-listing and hedonic indices, supply, days on market, price-cut rate, rents and gross yields, and what changed. Triggers on "thị trường", "giá khu", "market", "how is the market", "giá thuê", "lợi suất".
when_to_use: Market questions at city, ward or segment level.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-market — the landscape

1. Check coverage with `python3 -m vnrealty.cli coverage --json`: listings and observations per ward, type and month.
   Thin cells are reported as insufficient. If the user's ward is thin, offer a `re-find` run first.
2. Pull the numbers:
   - `market <ward|city> --as-of <date> --json` gives the price-per-m² table, indices, landscape and rents;
   - `market yields --json` gives gross yields by ward and type.
3. Read the numbers in the order: price level, trend (repeat index > hedonic index > raw medians), liquidity (days on
   market, cut rate), supply, rent yield vs the mortgage rate.
4. Add context from the news with WebSearch: city land-price reports (DKRA, Savills, batdongsan reports), credit
   conditions, planning decisions. Cite them, and keep them separate from the computed numbers.
5. Name the cycle stage from the evidence (e.g. "asking prices flat, cut rate rising, days on market lengthening:
   cooling"). Say what would change the read.
6. Run `report market <ward|city>` to write the HTML and Markdown.
