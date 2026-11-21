---
name: re-deal
description: Model a purchase or build on the deal engine: costs, loan (teaser, floating, grace), rent or business income, NOI, DSCR, IRR, NPV, break-evens, max loan, stress, and expected value over scenarios with kill triggers. Triggers on "tính toán", "có lời không", "dòng tiền", "vay bao nhiêu", "deal", "IRR", "EV", "cash flow".
when_to_use: Evaluating whether a specific purchase/build pays and under what conditions.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch, WebFetch
---

# re-deal

1. Build the deal JSON (Deal fields, VND).
   - Price comes from the listing; value_after from `value`.
   - Rent comes from `market rents --ward … --json`, never a guess.
   - Rates and loan terms come from the user or `reference/bank_lending.json`.
   - Build cost comes from `reference/build_costs.json`.
   - Presets: `deal preset build_rent|homestay|chdv|apartment|shophouse|land`.
2. Run `deal <file> --json` (metrics, stress, yearly table), then `ev <file> --json` (default scenarios: base, bear,
   bull, rate +3, vacancy). It returns EV, P(loss), P(IRR < hurdle) and fired kill triggers.
3. Verdict: does it clear the hurdle in the base case? Does it survive the bear case (DSCR, cash)? Is the price
   under value?
4. If the loan fails the DSCR test, show `loan_max`.
5. Record the decision as a paper deal (`ledger open …`) so it is graded later.
6. Offer `report deal <file>`. The deal dashboard includes the calculator, the formulas and the scale ladder.
