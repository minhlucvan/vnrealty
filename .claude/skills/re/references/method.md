# Method: how the desk turns evidence into a number

The edge is method. Vietnamese property is opaque in a few ways:
- listings are asking prices;
- transactions are under-declared;
- the same lot appears on five sites at three prices;
- planning news moves prices years before anything is built.

An investor who separates these, triangulates, and keeps score sees value others guess at.

## 1. Evidence classes (strongest first)
1. **Sale evidence.** Notarised price, a broker-confirmed close, an auction or court sale. These are rare. Record every
   one in `sale_evidence` with its source.
2. **Repeated asking prices for the same property.** A cut is informative. A listing that disappears after a cut
   probably sold near its last price.
3. **Cross-sectional asking prices.** Comps, the hedonic model and indices. They run high: apply the cited
   asking→sale haircut (`reference/market_params.json`).
4. **The official land-price table** (bảng giá đất). A floor and the tax basis, not a market value.
5. **Reconstructed history.** Index-moved anchors. Labelled `reconstructed`, always with bands.
6. **Judgement.** A catalyst's chance and uplift, an expert read. Allowed, but labelled `judgement` with its basis,
   and never presented as data.

## 2. Valuation = triangulation
Independent methods: comps, hedonic, index-moved purchase, and the official floor as a sanity check.
- `vnrealty.valuation.triangulate.combine` blends them.
- Weights are earned from the calibration record (`vnr calibrate`).
- If the methods disagree by more than their bands, the disagreement is the finding. Investigate before averaging.

## 3. Point in time
Every query takes `--as-of`. A backtest must use only what was captured by then. A capture's `seen_at` is what
counts, never a file date.

## 4. Projection
Market drift × catalysts (`projection.catalysts`):
- **bear** = no catalyst lands;
- **base** = each catalyst at its chance;
- **bull** = all of them land.

Monte Carlo (`projection.montecarlo`) adds price volatility and delay. Present the range and say what the base case
rests on.

## 5. Deals and EV
The deal engine (`deal.engine`) prices one deal month by month: build, lease-up, teaser and floating rate, sale.
- `deal.ev` weighs scenarios.
- A deal is attractive when its IRR clears the hurdle **in the base case**, it survives the bear case without a
  forced sale (DSCR, liquidity), and the price sits under the triangulated value.

## 6. Grading
- Every valuation is recorded. Every decision is a paper deal (`portfolio.ledger`).
- `vnr calibrate` scores MAPE, bias and band coverage.
- If an 80% band covers 50% of outcomes, the bands are too narrow. Widen them; do not explain them away.

## 7. Vietnamese specifics to check every time
- **Title.** Sổ hồng/sổ đỏ vs HĐMB vs giấy tay. Co-owners and spouse consent.
- **Planning.** The land-use code from the zoning map (ODT/ONT residential; DGT road; CXK green). Lộ giới (road
  boundary) setbacks can take part of a lot.
- **Access.** Kiệt (alley) width decides the price class: a car-wide kiệt vs a 2 m kiệt vs mặt tiền.
- **Taxes and fees.** 2% seller PIT on the transfer price, 0.5% registration fee, notary. See
  `vnr legal costs`.
- **Đà Nẵng since July 2025.** Districts are abolished and wards merged. Listings still say "Ngũ Hành Sơn" or
  "Hòa Quý". `geo.wards.match_ward` maps both.
