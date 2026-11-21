---
name: re-pricing
description: Price every listing on the yardstick its segment uses — land (price per buildable m², land residual, frontage), house (land + depreciated building), apartment (price/m² vs project, price-to-rent), shophouse (price per frontage metre, yield), homestay/CHDV (price per room, income value vs cap rate) — then score and rank them for profit. Triggers on "định giá theo loại", "rẻ hay đắt", "chỉ số giá", "lọc tin tốt", "pricing metrics", "rank listings", "which listings are cheap", "price per room", "land residual".
when_to_use: Ranking many listings or explaining whether one is cheap for its type. Use re-value for a single triangulated value with a band.
allowed-tools: Read, Grep, Glob, Bash(python3 -m vnrealty.cli:*), WebSearch
---

# re-pricing — relative value by property type

1. **Coverage.** Run `python3 -m vnrealty.cli coverage --json`. Relative metrics need peers. When a ward has thin
   peers, the scope widens (ward → wider area band → old district → city), and the scope used is always reported.
   If the user's target ward is thin, offer `re-find` first.
2. **One listing.** Run `price <listing> --json`. It returns the per-type metrics (each with its value, unit, basis
   and peer percentile or z-score), the 0–100 pricing score, its confidence, the three strongest and three weakest
   metrics, and red flags.
3. **Many listings.** Run `screen --rule pricing --ward … --ptype land,house,shophouse,apartment,homestay,chdv
   --max-price … --top 20 --json`. Each row carries its key metric, score, confidence, best-fit strategy and flags.
4. **Read the numbers as an investor would:**
   - **Land:** the land residual vs the asking price decides whether it is cheap. Price per buildable m² compares
     lots that allow different heights.
   - **House:** asking minus land value is what you pay for the building. Compare it with the depreciated cost.
   - **Apartment:** price/m² vs the same project. The rent multiple shows whether it is a yield play or a growth
     bet.
   - **Shophouse:** price per frontage metre and rent per frontage metre.
   - **Homestay / CHDV:** price per room and the implied cap rate vs the reference cap rate.

   A very low z-score means "too cheap: verify" (legal, planning, access, a fake listing). It is not a bargain until
   checked.
5. **Hand off** the top candidates to `re-analyze` (full team), or to `re-deal` / `strategy` for the best way to
   profit (buy and hold, rent, flip, build, subdivide, rental arbitrage).
6. **Report** with `report screen` for the ranked dashboard with a map, or `report listing <id>` for one listing.

Weights and parameters live in `reference/pricing_params.json`, each marked as sourced or judgement. When the
calibration record (`re-learn`) shows a metric predicting badly, propose new weights with the evidence.
