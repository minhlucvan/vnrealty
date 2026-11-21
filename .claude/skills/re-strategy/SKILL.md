---
name: re-strategy
description: Find the most profitable way to use an opportunity — buy and hold, long lease, build to rent, fix and flip, land bank, subdivide (tách thửa), rental arbitrage (lease and sublet as CHDV/homestay without owning), joint venture, homestay or CHDV business — ranked by risk-adjusted return for this investor; then allocate capital across candidates and find break-evens. Triggers on "cách nào lời nhất", "nên cho thuê hay bán", "thuê lại cho thuê", "lướt sóng", "tách thửa", "best strategy", "how to profit", "allocate my capital", "break-even".
when_to_use: After a listing or lot is valued (re-value / re-pricing), to decide how to make money on it; or to choose among several candidates with limited cash.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch
---

# re-strategy — every way to profit, ranked

1. **Profile.** If `data/portfolio/profile.json` is missing, ask the questionnaire
   (`python3 -m vnrealty.cli strategy profile questions --json`) and save the answers with
   `strategy profile from-answers`. Risk tolerance, time available and limits decide which strategies are allowed and
   how they are weighed.
2. **Opportunity file.** Write the facts:
   - price, area, ptype and ward;
   - the triangulated value (from `value`);
   - market rents per m² or per room (from `market rents`), never the seller's claim;
   - for homestay: rate per night and occupancy, with a cited source;
   - build cost (`reference/strategy_params.json` → market_reference);
   - for rental arbitrage: master rent, deposit months, fit-out and the sublet rent per room;
   - for subdivision: the minimum lot size. Đà Nẵng's QĐ 75/2026 per-ward minimum is unverified, so confirm it at the
     ward office.
3. **Evaluate.** Run `strategy evaluate <opportunity.json> --json`. For each applicable strategy it gives cash needed
   and peak, IRR, NPV, EV over the scenarios, P(loss), bear-case loss, liquidity, complexity, any fired kill
   triggers, and the explicit risk-adjusted score. Strategies that cannot be priced are listed with the missing
   inputs.
4. **Explain the winner and the runner-up:**
   - why it wins (yield, growth, speed, capital efficiency);
   - what kills it (its kill triggers);
   - what would flip the ranking. Run `strategy tornado` and `strategy break-even <field>` to find, for example, the
     rent or exit price at which the winner stops working.
5. **Several candidates, limited cash.** Collect the evaluated candidates, then run `strategy allocate
   candidates.json --cash <liquid cash> --json`. It returns the chosen set, totals, the binding constraint (cash,
   concentration, risk budget, liquidity) and the best candidate that did not fit, with the reason.
6. **Record** the decision as a paper deal (`ledger open …`) and offer `report strategy <subject>`.

Rental arbitrage and flips are fast and capital-light, but they are operating businesses with execution risk. The
complexity weight and the profile account for that. Never present a strategy's IRR without its bear case.
