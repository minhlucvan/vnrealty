# vnrealty

A quantitative real-estate investing desk for Vietnam, starting with **Đà Nẵng**. It is built for Claude Code and
runs on the investor's own Chrome.

It covers the whole investing process:
- **scout** listings across sites, Google Maps, zoning maps and public groups, using injected read-only extractors;
- **track** prices over time (every sighting is kept);
- **read** the market: indices, supply, liquidity, rents and yields;
- **value** a property by triangulation: comps with the asking→sale haircut, a hedonic model, the official land
  table, the index-moved purchase price;
- **check** zoning and infrastructure, and **project** prices from catalysts plus Monte Carlo;
- **model** deals and their expected value, **compare** them, and **plan** the best use of a property;
- **finance**: affordability and a purchase ladder;
- **operate** units: leases, the monthly close, risk;
- **check legal**: due diligence, taxes and fees;
- **grade** every estimate against what happened.

Inspired by [ai-realestate-claude](https://github.com/zubair-trabzada/ai-realestate-claude) (MIT). This repo adds a
local data layer, tested quant libraries, citations and the Vietnamese market rules.

> Decision support for the owner, not financial or legal advice. Asking prices are not sale prices.

## Principles
The libraries compute and the agents orchestrate. A missing number returns `Insufficient`, never a default. Every
input is cited and dated. Every query can be run as of a past date. Private data stays in `data/`, which is
gitignored. See [CLAUDE.md](CLAUDE.md).

## Use
```bash
python3 -m unittest discover -s tests -t .     # stdlib only, Python ≥ 3.12
python3 web/check_parity.py                    # browser ports == Python engine (needs node)
```
In Claude Code, start with `/re` (for example "/re thị trường Ngũ Hành Sơn", "/re định giá listing 42",
"/re tìm đất dưới 3 tỷ").

## Status
Work in progress. Done: the deal engine, the portfolio ladder, the store, stats, reports, skills, agents and
workflows. In progress: listings and mining, market, valuation, projection, infrastructure, decisions, portfolio
and legal, the strategy layer, and the `vnr` CLI.
