"""The strategy registry: every way to profit from one opportunity, each expressed on the one deal engine.

A **strategy** is a function ``(opportunity, assumptions) -> StrategyDeal | Insufficient``. Both arguments are plain
dicts; they are merged over the strategy's defaults from ``reference/strategy_params.json`` (common, then the
strategy's own), with ``assumptions`` winning over ``opportunity``. The defaults are conventions and judgement only
(tax rates, vacancy conventions, OTA commission, ...); **market numbers are never defaulted** — a strategy whose
required keys are missing returns :class:`~vnrealty.types.Insufficient` listing them.

A :class:`StrategyDeal` wraps a :class:`~vnrealty.deal.engine.Deal` with three things the engine's single shape cannot
say, all computed *on the engine's own schedule rows* (the engine is not modified):

* ``horizon_months`` — the exit month. The engine sells at ``hold_years × 12``; a 6-month flip or a subdivision that
  exits at month 15 is the engine run for ``ceil(months / 12)`` years and **sold at row ``horizon_months``**:
  equity flows are months 0..H and the sale is ``value_H × (1 − sell_costs) − balance_H``.
* ``extra_flows`` — owner cash flows outside the deal, ``(month, VND)``; month ``-1`` means the horizon month. Used
  for a master-lease deposit (out at month 0, back at the end).
* ``owner_share`` / ``land_out`` — a joint venture, where the landowner puts in the land (``land_out`` VND at month 0)
  and receives ``owner_share`` of each month's NOI and of the net sale; the builder pays the build
  (:func:`vnrealty.plan.options.jv_owner`).

:func:`flows` returns the owner's monthly equity flows (VND, index 0 = today, negative = money in) and
:func:`metrics` the comparable numbers (IRR via ``engine.irr_monthly``, NPV at the hurdle, profit, peak cash,
payback, stabilised DSCR, worst month). For a plain deal held to ``hold_years`` with no extras, both agree exactly
with ``engine.analyse`` and ``ev.equity_flows`` (tested).

Strategies (``STRATEGIES``): buy_hold, buy_rent_long, build_to_rent, fix_flip, land_bank, subdivide,
rental_arbitrage, joint_venture, buy_to_homestay, buy_to_chdv — see each function. Money VND, area m², rates annual
fractions, rents per month, durations in months unless named ``_years``.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from vnrealty.deal.engine import Deal, _schedule, analyse, irr_monthly
from vnrealty.plan.options import DAYS_PER_MONTH, Lot, jv_owner, options as lot_options
from vnrealty.types import Insufficient

__all__ = ["StrategyDeal", "STRATEGIES", "REQUIRED", "params", "strategy_defaults", "build", "build_all", "flows",
           "metrics", "liquidity_months", "complexity"]

_REF = Path(__file__).resolve().parents[2] / "reference" / "strategy_params.json"
_PARAMS: dict | None = None


def params() -> dict:
    """The parsed ``reference/strategy_params.json`` (cached)."""
    global _PARAMS
    if _PARAMS is None:
        _PARAMS = json.loads(_REF.read_text(encoding="utf-8"))
    return _PARAMS


def _vals(block: dict) -> dict:
    return {k: v["value"] for k, v in block.items() if isinstance(v, dict) and "value" in v}


def strategy_defaults(name: str) -> dict:
    """Common + strategy-specific default values (conventions/judgement only) for strategy ``name``."""
    p = params()
    return {**_vals(p["common"]), **_vals(p["defaults"].get(name, {}))}


def liquidity_months(name: str) -> float:
    """Judgement: months to turn strategy ``name`` back into cash (``strategy_params.json``)."""
    return float(params()["liquidity_months"][name])


def complexity(name: str) -> float:
    """Judgement: execution complexity 1 (passive) .. 5 (hard) of strategy ``name``."""
    return float(params()["complexity"][name])


@dataclass(frozen=True)
class StrategyDeal:
    """One strategy applied to one opportunity, ready for :func:`flows` / :func:`metrics`."""
    strategy: str
    deal: Deal
    horizon_months: int                                   # exit month (≤ deal.hold_years × 12)
    extra_flows: tuple = ()                               # ((month, VND), ...); month -1 = the horizon month
    owner_share: float | None = None                      # joint venture: landowner's share of NOI and sale
    land_out: float | None = None                         # joint venture: landowner's outflow at month 0 (VND)
    has_income: bool = True
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------- flows and metrics

def _horizon(sd: StrategyDeal) -> int:
    return max(1, min(sd.horizon_months, sd.deal.hold_years * 12))


def flows(sd: StrategyDeal) -> list[float]:
    """The owner's monthly equity cash flows, months 0..H (VND; negative = money in)."""
    d = sd.deal
    H = _horizon(sd)
    rows = _schedule(d)
    if sd.owner_share is not None:
        s = sd.owner_share
        eq = [-(sd.land_out or 0.0)] + [s * rows[t]["noi"] for t in range(1, H + 1)]
        eq[H] += s * rows[H]["value"] * (1 - d.sell_costs)
    else:
        eq = [-rows[0]["spend"]] + [rows[t]["net"] for t in range(1, H + 1)]
        eq[H] += rows[H]["value"] * (1 - d.sell_costs) - rows[H]["balance"]
    for m, amt in sd.extra_flows:
        eq[H if m == -1 else m] += amt
    return eq


def metrics(sd: StrategyDeal, hurdle: float | None = None) -> dict:
    """Comparable numbers for one strategy deal.

    ``irr`` (annual, ``None`` if the flows have no sign change), ``npv`` at ``hurdle`` (annual; default the deal's),
    ``profit`` (Σ flows, VND), ``peak_cash`` (largest cumulative own money out before the exit, VND), ``cash_in``
    (own money at month 0), ``payback_month`` (first month the cumulative flow, exit included, is ≥ 0),
    ``horizon_months``, ``dscr`` (stabilised, from ``analyse``; ``None`` without debt or without income),
    ``stable_cash`` (stabilised monthly cash, VND; for a JV the owner's share), ``worst_month_cash`` (lowest
    monthly cash between opening and exit; from month 1 for strategies without income), ``ltv``, ``loan``.
    """
    d = sd.deal
    h = d.hurdle if hurdle is None else hurdle
    eq = flows(sd)
    H = len(eq) - 1
    mh = (1 + h) ** (1 / 12) - 1
    cum, peak, payback = 0.0, 0.0, None
    for t, c in enumerate(eq):
        cum += c
        if t < H:
            peak = min(peak, cum)
        if payback is None and t > 0 and cum >= 0:
            payback = t
    a = analyse(d)
    rows = _schedule(d)[1:H + 1]
    jv = sd.owner_share is not None
    if jv:
        st_cash = a["stable"]["noi"] * sd.owner_share
        dscr = None
        worst = min((sd.owner_share * r["noi"] for r in rows[d.build_months + d.lease_up_months:]), default=0.0)
        loan = 0.0
    else:
        st_cash = a["stable"]["cash"]
        dscr = a["stable"]["dscr"] if sd.has_income else None
        start = (d.build_months + d.lease_up_months + d.ramp_months) if sd.has_income else 0
        worst = min((r["cash"] for r in rows[start:]), default=0.0)
        loan = a["loan_used"]
    return {"strategy": sd.strategy, "irr": irr_monthly(eq), "npv": sum(c / (1 + mh) ** t for t, c in enumerate(eq)),
            "profit": sum(eq), "peak_cash": -peak, "cash_in": -eq[0], "payback_month": payback, "horizon_months": H,
            "dscr": dscr, "debt_service": 0.0 if jv else a["stable"]["debt_service"], "stable_cash": st_cash,
            "worst_month_cash": worst, "ltv": 0.0 if jv else a["ltv"], "loan": loan, "hurdle": h}


# ---------------------------------------------------------------- inputs

def _merge(name: str, opportunity: dict, assumptions: dict) -> dict:
    return {**strategy_defaults(name), **(opportunity or {}), **(assumptions or {})}


def _need(name: str, x: dict, keys: list[str]) -> Insufficient | None:
    miss = [k for k in keys if x.get(k) is None]
    if x.get("loan_ltv") and "mortgage_rate" not in keys and x.get("mortgage_rate") is None:
        miss.append("mortgage_rate")
    return Insufficient(f"strategy:{name}", "missing: " + ", ".join(miss), {"missing": miss}) if miss else None


def _loan_fields(x: dict, base: float) -> dict:
    ltv = x.get("loan_ltv") or 0.0
    rate = x.get("mortgage_rate") or 0.0
    teaser = x.get("teaser_rate")
    return {"loan": base * ltv, "float_rate": rate, "teaser_rate": teaser if teaser is not None else rate,
            "teaser_years": int(x.get("teaser_years", 0)) if teaser is not None else 0,
            "term_years": int(x["term_years"]), "grace_months": int(x.get("grace_months", 0))}


def _common(x: dict) -> dict:
    return {"buy_costs": x["buy_costs"], "sell_costs": x["sell_costs"], "cost_growth": x["cost_growth"],
            "hurdle": x["hurdle"], "dscr_min": x.get("dscr_min", 1.2), "building_life_years": 0, "build_cost": 0.0,
            "build_months": 0, "ramp_months": 0, "cogs": 0.0, "staff": 0.0}


_HOLD = ["price", "market_value", "rent", "rent_growth", "price_growth", "hurdle", "hold_years", "renovation",
         "running_costs"]

REQUIRED: dict[str, list[str]] = {
    "buy_hold": _HOLD,
    "buy_rent_long": ["price", "market_value", "rent_growth", "price_growth", "hurdle", "hold_years", "renovation",
                      "running_costs"],  # + rent or long_lease_rent
    "build_to_rent": ["price", "market_value", "area_m2", "hurdle", "hold_years", "price_growth", "rent_growth",
                      "buildable_ratio", "max_floors", "build_cost_m2", "unit_size_m2", "unit_rent", "fit_out_per_unit",
                      "running_cost_per_unit", "build_ltv"],
    "fix_flip": ["price", "flip_renovation", "after_repair_value", "hurdle", "running_costs"],
    "land_bank": ["price", "market_value", "price_growth", "hurdle", "hold_years"],
    "subdivide": ["price", "area_m2", "lots", "lot_size_m2", "small_lot_price_m2", "subdivision_cost",
                  "subdivision_months", "min_lot_m2", "price_growth", "hurdle"],
    "rental_arbitrage": ["master_rent", "lease_years", "arbitrage_fit_out", "sublet_mode", "rent_growth", "hurdle"],
    "joint_venture": ["price", "market_value", "area_m2", "hurdle", "hold_years", "price_growth", "rent_growth",
                      "buildable_ratio", "max_floors", "build_cost_m2", "unit_size_m2", "unit_rent", "fit_out_per_unit",
                      "running_cost_per_unit"],
    "buy_to_homestay": ["price", "market_value", "homestay_rooms", "homestay_adr", "homestay_occ", "homestay_staff",
                        "homestay_fit_out", "running_costs",
                        "rent_growth", "price_growth", "hurdle", "hold_years"],
    "buy_to_chdv": ["price", "market_value", "chdv_units", "chdv_unit_rate", "chdv_occ", "chdv_staff", "chdv_fit_out",
                    "running_costs",
                    "rent_growth", "price_growth", "hurdle", "hold_years"],
}


def _hold_deal(name: str, x: dict, **o) -> Deal:
    d = Deal(price=x["price"], renovation=x["renovation"], value_after=x.get("value_after_renovation", x["market_value"]),
             lease_up_months=int(x.get("lease_up_months", 2)), rent=x.get("rent", 0.0), rent_growth=x["rent_growth"],
             vacancy=x.get("vacancy", 0.0), management=x.get("management", 0.0), running_costs=x["running_costs"],
             rent_tax=x["rent_tax"], price_growth=x["price_growth"], hold_years=int(x["hold_years"]),
             **_common(x), **_loan_fields(x, x["price"]))
    return replace(d, **o)


# ---------------------------------------------------------------- strategies

def buy_hold(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Buy, renovate lightly (``renovation`` VND, ``lease_up_months`` empty), rent (``rent`` per month, conventional
    ``vacancy``/``management``), sell at ``hold_years``. ``value_after_renovation`` defaults to ``market_value``
    (the market value of the property as bought — not a defaulted market number: it is a required key)."""
    x = _merge("buy_hold", opportunity, assumptions)
    if (miss := _need("buy_hold", x, REQUIRED["buy_hold"])):
        return miss
    d = _hold_deal("buy_hold", x)
    return StrategyDeal("buy_hold", d, d.hold_years * 12)


def buy_rent_long(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """As :func:`buy_hold` on a multi-year single lease: low vacancy, owner-managed, ``long_lease_rent`` per month
    (or ``rent × long_lease_rent_factor`` — judgement discount for certainty — when only ``rent`` is given)."""
    x = _merge("buy_rent_long", opportunity, assumptions)
    keys = list(REQUIRED["buy_rent_long"])
    if x.get("long_lease_rent") is None and x.get("rent") is None:
        keys.append("rent")
    if (miss := _need("buy_rent_long", x, keys)):
        return miss
    rent = x["long_lease_rent"] if x.get("long_lease_rent") is not None else x["rent"] * x["long_lease_rent_factor"]
    d = _hold_deal("buy_rent_long", {**x, "rent": rent})
    return StrategyDeal("buy_rent_long", d, d.hold_years * 12, meta={"rent_basis": "long_lease_rent" if
                        x.get("long_lease_rent") is not None else "rent × long_lease_rent_factor"})


def _lot(x: dict) -> Lot:
    keys = {f for f in Lot.__dataclass_fields__}
    kw = {k: x[k] for k in keys if k in x and x[k] is not None}
    kw["value"] = x["market_value"]
    kw["mortgage_rate"] = x.get("mortgage_rate")
    kw["hold_years"] = int(x["hold_years"])
    kw["sell_costs"] = x["sell_costs"]
    kw["rent_tax"] = x["rent_tax"]
    kw["business_tax"] = x["business_tax"]
    kw["cost_growth"] = x["cost_growth"]
    kw["term_years"] = int(x["term_years"])
    return Lot(**kw)


def build_to_rent(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Buy land, build studios over ``build_months`` (layout and costs from :func:`vnrealty.plan.options.layout`:
    footprint = area × ``buildable_ratio``, GFA × ``build_cost_m2``, units = ⌊GFA × efficiency / unit size⌋) and
    rent them; the loan is ``build_ltv`` × build cost. The price paid is ``price`` (+ buy costs); the land is worth
    ``market_value`` today and grows at ``price_growth``. Lot conventions (efficiency, build months, building life)
    are those documented in ``plan.options.Lot``."""
    x = _merge("build_to_rent", opportunity, assumptions)
    keys = list(REQUIRED["build_to_rent"])
    if x.get("build_ltv"):
        keys.append("mortgage_rate")
    if (miss := _need("build_to_rent", x, keys)):
        return miss
    lot = _lot(x)
    d = lot_options(lot)["build_studios"]
    if isinstance(d, Insufficient):
        return Insufficient("strategy:build_to_rent", d.reason)
    d = replace(d, price=x["price"], buy_costs=x["buy_costs"], value_after=x["market_value"], hurdle=x["hurdle"])
    return StrategyDeal("build_to_rent", d, d.hold_years * 12, meta={"units": int(round(d.rent / x["unit_rent"]))})


def fix_flip(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Buy below value, renovate (``flip_renovation`` VND), sell after ``flip_months`` (default judgement 6) at ``after_repair_value`` (today's
    market value once renovated), with ``flip_price_growth`` (default 0 — a flip is not underwritten on market
    drift). No rent. ``running_costs`` (per month) are paid while held; the loan (``loan_ltv`` × price) is
    interest-only for the whole flip (``grace_months`` = flip months). The engine runs for ``ceil(months/12)`` years
    and the sale is taken at row ``flip_months``."""
    x = _merge("fix_flip", opportunity, assumptions)
    if (miss := _need("fix_flip", x, REQUIRED["fix_flip"])):
        return miss
    m = int(x["flip_months"])
    if m < 1:
        return Insufficient("strategy:fix_flip", f"flip_months must be ≥ 1, got {m}")
    lf = _loan_fields(x, x["price"])
    lf["grace_months"] = max(lf["grace_months"], m)
    d = Deal(price=x["price"], renovation=x["flip_renovation"], value_after=x["after_repair_value"], lease_up_months=0,
             rent=0.0, rent_growth=0.0, vacancy=0.0, management=0.0, running_costs=x["running_costs"], rent_tax=0.0,
             price_growth=x["flip_price_growth"], hold_years=math.ceil(m / 12), **_common(x), **lf)
    return StrategyDeal("fix_flip", d, m, has_income=False, meta={"flip_months": m})


def land_bank(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Buy land, earn nothing, pay ``holding_cost_rate`` × price per year (judgement) as running costs, sell at
    ``hold_years``. All value is ``price_growth`` (projection and catalysts are estimated elsewhere and passed in)."""
    x = _merge("land_bank", opportunity, assumptions)
    if (miss := _need("land_bank", x, REQUIRED["land_bank"])):
        return miss
    d = Deal(price=x["price"], renovation=0.0, value_after=x["market_value"], lease_up_months=0, rent=0.0,
             rent_growth=0.0, vacancy=0.0, management=0.0, running_costs=x["price"] * x["holding_cost_rate"] / 12,
             rent_tax=0.0, price_growth=x["price_growth"], hold_years=int(x["hold_years"]), **_common(x),
             **_loan_fields(x, x["price"]))
    return StrategyDeal("land_bank", d, d.hold_years * 12, has_income=False)


def subdivide(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Tách thửa: buy a large lot (``price``, ``area_m2``), pay ``subdivision_cost`` (survey, fees, road and
    infrastructure, conversion — VND, up front) and wait ``subdivision_months``, then sell ``lots`` lots of
    ``lot_size_m2`` at ``small_lot_price_m2`` (today's VND/m², growing at ``price_growth``) after ``sell_months``
    (default judgement 6) — modelled as one sale at month subdivision + sell months. Holding cost
    ``holding_cost_rate`` × price per year (judgement) while held. Refused when ``lots × lot_size_m2 > area_m2`` or ``lot_size_m2 < min_lot_m2``
    (the ward's legal minimum, Đà Nẵng QĐ 75/2026/QĐ-UBND Phụ lục III — required, never defaulted; see
    ``strategy_params.json`` ``tach_thua_da_nang``)."""
    x = _merge("subdivide", opportunity, assumptions)
    if (miss := _need("subdivide", x, REQUIRED["subdivide"])):
        return miss
    n, size = int(x["lots"]), float(x["lot_size_m2"])
    if n < 2:
        return Insufficient("strategy:subdivide", f"lots must be ≥ 2, got {n}")
    if n * size > x["area_m2"] + 1e-9:
        return Insufficient("strategy:subdivide", f"{n} × {size} m² exceeds the lot's {x['area_m2']} m²")
    if size < x["min_lot_m2"]:
        return Insufficient("strategy:subdivide", f"lot size {size} m² is below the legal minimum {x['min_lot_m2']} m²")
    H = int(x["subdivision_months"]) + int(x["sell_months"])
    sale_value = n * size * x["small_lot_price_m2"]
    d = Deal(price=x["price"], renovation=x["subdivision_cost"], value_after=sale_value, lease_up_months=0, rent=0.0,
             rent_growth=0.0, vacancy=0.0, management=0.0, running_costs=x["price"] * x["holding_cost_rate"] / 12, rent_tax=0.0,
             price_growth=x["price_growth"], hold_years=math.ceil(H / 12), **_common(x), **_loan_fields(x, x["price"]))
    return StrategyDeal("subdivide", d, H, has_income=False,
                        meta={"sale_value_today": sale_value, "sold_m2": n * size, "road_m2": x["area_m2"] - n * size,
                              "legal_note": "verify min_lot_m2 against QĐ 75/2026/QĐ-UBND Phụ lục III for the ward"})


def _sublet(x: dict, mode: str) -> tuple[dict, list[str]] | tuple[None, list[str]]:
    if mode == "homestay":
        need = [k for k in ("homestay_rooms", "homestay_adr", "homestay_occ", "homestay_staff") if x.get(k) is None]
        if need:
            return None, need
        return {"rent": x["homestay_rooms"] * x["homestay_adr"] * DAYS_PER_MONTH * x["homestay_occ"],
                "management": x["ota_commission"], "cogs": x["homestay_cogs"], "staff": x["homestay_staff"], "vacancy": 0.0, "rent_tax": x["business_tax"]}, []
    if mode == "chdv":
        need = [k for k in ("chdv_units", "chdv_unit_rate", "chdv_occ", "chdv_staff") if x.get(k) is None]
        if need:
            return None, need
        return {"rent": x["chdv_units"] * x["chdv_unit_rate"] * x["chdv_occ"], "management": x["chdv_management"],
                "cogs": x["chdv_cogs"], "staff": x["chdv_staff"], "vacancy": 0.0, "rent_tax": x["business_tax"]}, []
    return None, [f"sublet_mode must be 'homestay' or 'chdv', got {mode!r}"]


def _business_defaults() -> dict:
    return {**strategy_defaults("buy_to_homestay"), **strategy_defaults("buy_to_chdv")}


def rental_arbitrage(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Master lease and sublet (thuê lại cho thuê) — no ownership: ``price = value_after = 0``, no loan, nothing to
    sell. ``arbitrage_fit_out`` (VND) is the up-front spend (engine ``renovation``), ``fit_out_months`` empty; the master rent
    ``master_rent`` (per month) plus ``other_running_costs`` are the engine's running costs from month 1, escalating
    at ``master_rent_escalation`` per year (carried by ``cost_growth``, which also grows staff). Sublet income per
    ``sublet_mode``: ``'homestay'`` = homestay_rooms × homestay_adr × 30.4 × homestay_occ with OTA commission and cleaning
    cogs, or ``'chdv'`` = chdv_units × chdv_unit_rate × chdv_occ; business tax applies. ``hold_years = lease_years``.

    **The deposit** (``deposit_months`` × master rent, default judgement 3) is not an engine field: it is an extra
    owner flow, out at month 0 and returned at the lease end (``extra_flows``), so the IRR from :func:`flows` /
    :func:`metrics` is the deposit-adjusted IRR. ``meta['irr_engine']`` keeps the engine's IRR without it. A
    forfeited deposit is a scenario the caller must model (override ``extra_flows``)."""
    given = {**(opportunity or {}), **(assumptions or {})}
    mode_defaults = strategy_defaults("buy_to_chdv" if given.get("sublet_mode") == "chdv" else "buy_to_homestay")
    x = {**_business_defaults(), **mode_defaults, **strategy_defaults("rental_arbitrage"), **given}
    if (miss := _need("rental_arbitrage", x, REQUIRED["rental_arbitrage"])):
        return miss
    inc, need = _sublet(x, x["sublet_mode"])
    if inc is None:
        return Insufficient("strategy:rental_arbitrage", "missing: " + ", ".join(need), {"missing": need})
    years = int(x["lease_years"])
    if years < 1:
        return Insufficient("strategy:rental_arbitrage", f"lease_years must be ≥ 1, got {years}")
    deposit = x["deposit_months"] * x["master_rent"]
    c = _common(x)
    c.update(buy_costs=0.0, sell_costs=0.0, cost_growth=x["master_rent_escalation"])
    d = Deal(price=0.0, renovation=x["arbitrage_fit_out"], value_after=0.0, lease_up_months=int(x["fit_out_months"]),
             rent_growth=x["rent_growth"], running_costs=x["master_rent"] + (x.get("other_running_costs") or 0.0),
             price_growth=0.0, hold_years=years, loan=0.0, float_rate=0.0, teaser_rate=0.0, teaser_years=0,
             term_years=int(x["term_years"]), **{**c, **inc, "ramp_months": int(x["ramp_months"])})
    a = analyse(d)
    return StrategyDeal("rental_arbitrage", d, years * 12, extra_flows=((0, -deposit), (-1, deposit)),
                        meta={"deposit": deposit, "irr_engine": a["irr"], "mode": x["sublet_mode"]})


def joint_venture(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Landowner + builder (hợp tác kinh doanh): the investor buys the land (``price`` + buy costs is the owner's
    outflow), a partner pays the build with no loan, the studios are let, and the owner receives ``jv_owner_share``
    of NOI and of the net sale — by default the land's share of land (at ``market_value``) + build + fit-out, as in
    :func:`vnrealty.plan.options.jv_owner` (whose caveat applies: a BCC returning the land is not modelled)."""
    x = _merge("joint_venture", opportunity, assumptions)
    if (miss := _need("joint_venture", x, REQUIRED["joint_venture"])):
        return miss
    lot = replace(_lot(x), build_ltv=0.0)
    d = lot_options(lot)["jv"]
    if isinstance(d, Insufficient):
        return Insufficient("strategy:joint_venture", d.reason)
    d = replace(d, hurdle=x["hurdle"])
    share = x.get("jv_owner_share")
    basis = "given"
    if share is None:
        share = x["market_value"] / (x["market_value"] + d.build_cost + d.renovation)
        basis = "land's share of land + build + fit-out"
    land_out = x["price"] * (1 + x["buy_costs"])
    return StrategyDeal("joint_venture", d, d.hold_years * 12, owner_share=share, land_out=land_out,
                        meta={"share_basis": basis})


def _business(name: str, x: dict, inc: dict, fit_out: float) -> StrategyDeal:
    d = _hold_deal(name, {**x, "renovation": fit_out, "rent": inc["rent"], "vacancy": 0.0, "management": inc["management"],
                          "rent_tax": inc["rent_tax"]},
                   cogs=inc["cogs"], staff=inc["staff"], ramp_months=int(x["ramp_months"]))
    return StrategyDeal(name, d, d.hold_years * 12)


def buy_to_homestay(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Buy, fit out (``homestay_fit_out`` VND) and run as a homestay: revenue = ``homestay_rooms`` ×
    ``homestay_adr`` (per room-night) × 30.4 × ``homestay_occ``; ``ota_commission`` (sourced ~15%) as management,
    ``homestay_cogs`` (judgement), ``homestay_staff`` per month, business tax
    (5% VAT + 2% PIT), revenue ramping over ``ramp_months``."""
    x = _merge("buy_to_homestay", opportunity, assumptions)
    if (miss := _need("buy_to_homestay", x, REQUIRED["buy_to_homestay"])):
        return miss
    inc, _ = _sublet(x, "homestay")
    return _business("buy_to_homestay", x, inc, x["homestay_fit_out"])


def buy_to_chdv(opportunity: dict, assumptions: dict) -> StrategyDeal | Insufficient:
    """Buy a building, fit it out (``chdv_fit_out`` VND) and run it as serviced apartments (CHDV): revenue =
    ``chdv_units`` × ``chdv_unit_rate`` (per unit per month at full occupancy) × ``chdv_occ``;
    ``chdv_management``/``chdv_cogs`` (judgement), ``chdv_staff`` per month, business tax."""
    x = _merge("buy_to_chdv", opportunity, assumptions)
    if (miss := _need("buy_to_chdv", x, REQUIRED["buy_to_chdv"])):
        return miss
    inc, _ = _sublet(x, "chdv")
    return _business("buy_to_chdv", x, inc, x["chdv_fit_out"])


STRATEGIES: dict[str, Callable[[dict, dict], StrategyDeal | Insufficient]] = {
    "buy_hold": buy_hold, "buy_rent_long": buy_rent_long, "build_to_rent": build_to_rent, "fix_flip": fix_flip,
    "land_bank": land_bank, "subdivide": subdivide, "rental_arbitrage": rental_arbitrage,
    "joint_venture": joint_venture, "buy_to_homestay": buy_to_homestay, "buy_to_chdv": buy_to_chdv,
}


def build(name: str, opportunity: dict, assumptions: dict | None = None) -> StrategyDeal | Insufficient:
    """Build strategy ``name`` for an opportunity. Raises ``ValueError`` on an unknown name."""
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; known: {sorted(STRATEGIES)}")
    return STRATEGIES[name](opportunity, assumptions or {})


def build_all(opportunity: dict, assumptions: dict | None = None, names: list[str] | None = None) -> dict:
    """``{name: StrategyDeal | Insufficient}`` for ``names`` (default all)."""
    return {n: build(n, opportunity, assumptions) for n in (names or list(STRATEGIES))}
