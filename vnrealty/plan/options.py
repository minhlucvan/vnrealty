"""What to do with one lot: price every realistic option on the same deal engine and rank them.

Generalised from a hand-built page that compared, for one plot, keeping it empty, leasing the bare land, building
rentable studios (with or without a ground-floor shop, or on fewer floors), a joint venture and selling. Here the
lot is a :class:`Lot` and every option is a :class:`~vnrealty.deal.engine.Deal`, so they are comparable.

**The land is counted at what it would sell for today** (``Lot.value``) in every option: keeping it is choosing not
to have that money. Each Deal therefore starts with an outflow equal to ``value`` (plus any build money), and the
sell options model the sale as that same outflow turned into proceeds net of ``sell_costs`` (the selling cost is
carried in the engine's ``renovation`` slot so the up-front total is exactly ``value``; its ``renovation_gain`` in
the split is therefore the selling cost, negative).

Layout (for the build options): footprint = ``area_m2 × buildable_ratio``; gross floor area (GFA) = footprint ×
floors; lettable units = ⌊GFA × ``efficiency`` / ``unit_size_m2``⌋; the shop variant gives the ground floor to a
shop and fills only the floors above. Build cost = GFA × ``build_cost_m2``; the loan is ``build_ltv`` × build cost.

Options: ``idle``, ``lease_land``, ``build_studios``, ``build_shop_studios``, ``build_small`` (one floor fewer than
``max_floors``), ``chdv`` (serviced apartments run as a business), ``homestay`` (rooms let by the night),
``jv`` (a builder pays the build with no loan; the landowner gets ``jv_owner_share`` of income and sale — by default
the land's share of total contribution), ``sell_deposit`` (sell, money on term deposit), ``sell_buy_rental`` (sell,
buy an existing rental outright with the proceeds).

**Missing inputs are not defaulted.** Market numbers — rents, ADR, build cost, rates, growth, hurdle — default to
``None``; an option whose inputs are missing comes back as :class:`~vnrealty.types.Insufficient` naming them. The
fields that do carry defaults are conventions or judgement, documented beside each one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from vnrealty.deal.engine import Deal, _schedule, analyse, irr_monthly
from vnrealty.types import Insufficient

__all__ = ["Lot", "options", "evaluate", "break_even_rent", "layout", "jv_owner", "OPTION_NAMES"]

DAYS_PER_MONTH = 365 / 12

OPTION_NAMES = ["idle", "lease_land", "build_studios", "build_shop_studios", "build_small", "chdv", "homestay",
                "jv", "sell_deposit", "sell_buy_rental"]


@dataclass(frozen=True)
class Lot:
    """One lot and the market around it. Money VND, area m², rates annual fractions, rents per month."""
    value: float                                  # what the land would sell for today
    area_m2: float
    buildable_ratio: float | None = None          # mật độ xây dựng: footprint / lot area (zoning)
    max_floors: int | None = None                 # floors allowed (zoning, alley width)
    build_cost_m2: float | None = None            # turnkey cost per m² of GFA
    unit_size_m2: float | None = None             # net area of one studio / serviced unit
    unit_rent: float | None = None                # one studio, per month
    shop_rent: float | None = None                # ground-floor shop, per month
    land_lease_rent: float | None = None          # bare land (parking, stall), per month
    homestay_adr: float | None = None             # average daily rate per room-night
    homestay_occ: float | None = None             # share of nights sold
    homestay_rooms: int | None = None             # None = the layout's unit count
    homestay_staff: float | None = None           # per month
    chdv_unit_rate: float | None = None           # serviced-apartment revenue per unit per month at full occupancy
    chdv_occ: float | None = None
    chdv_staff: float | None = None               # per month
    fit_out_per_unit: float | None = None         # furniture, appliances per unit
    running_cost_per_unit: float | None = None    # upkeep, utilities, fees per unit per month
    deposit_rate: float | None = None             # 12-month term deposit
    mortgage_rate: float | None = None            # floating construction / mortgage rate
    teaser_rate: float | None = None              # None = no teaser period
    teaser_years: int = 0
    build_ltv: float | None = None                # loan / build cost
    hurdle: float | None = None
    price_growth: float | None = None             # land price growth
    rent_growth: float | None = None
    rental_yield_gross: float | None = None       # for sell_buy_rental: rent·12 / price of the rental bought
    rental_price_growth: float | None = None
    rental_running_rate: float | None = None      # running costs per year / price of the rental bought
    rental_buy_costs: float = 0.02                # registration 0.5% + notary + broker (see reference/vn_tax_fees.json)
    rental_vacancy: float = 0.08                  # judgement
    jv_owner_share: float | None = None           # None = land's share of land + build + fit-out
    sell_costs: float = 0.03                      # 2% seller PIT (sourced) + ~1% broker (judgement)
    hold_years: int = 10
    term_years: int = 15
    cost_growth: float = 0.04                     # judgement: VN construction cost inflation
    efficiency: float = 0.75                      # judgement: lettable / gross (stairs, corridors, walls)
    build_months: int = 8                         # judgement: a 3-5 floor townhouse build
    lease_up_months: int = 3
    building_life_years: int = 30                 # judgement: straight-line wear of the building's value
    ramp_months: int = 6                          # business options: months to full revenue (judgement)
    vacancy: float = 0.10                         # judgement for studio lets
    management: float = 0.05
    rent_tax: float = 0.10                        # individual lessor: 5% VAT + 5% PIT on rent (Thông tư 40/2021/TT-BTC)
    business_tax: float = 0.07                    # accommodation household business: 5% VAT + 2% PIT (Thông tư 40/2021/TT-BTC)
    homestay_management: float = 0.15             # judgement: OTA commission + cleaning contractor
    homestay_cogs: float = 0.10                   # judgement: linen, amenities, breakfast
    chdv_management: float = 0.08                 # judgement
    chdv_cogs: float = 0.05                       # judgement: consumables, laundry
    idle_holding_cost: float = 0.0                # per month: land tax, fencing
    dscr_min: float = 1.2


def layout(lot: Lot, floors: int, shop: bool = False) -> dict | Insufficient:
    """Footprint, GFA (m²), lettable units and build cost (VND) for ``floors`` floors; ``shop`` gives the ground
    floor to a shop. Insufficient when a zoning or cost input is missing."""
    miss = [k for k in ("buildable_ratio", "build_cost_m2", "unit_size_m2") if getattr(lot, k) is None]
    if miss:
        return Insufficient("layout", "missing: " + ", ".join(miss))
    if floors < 1:
        return Insufficient("layout", f"floors must be ≥ 1, got {floors}")
    footprint = lot.area_m2 * lot.buildable_ratio
    gfa = footprint * floors
    res_floors = floors - 1 if shop else floors
    units = math.floor(footprint * res_floors * lot.efficiency / lot.unit_size_m2)
    return {"floors": floors, "footprint_m2": footprint, "gfa_m2": gfa, "units": units, "shop": shop,
            "build_cost": gfa * lot.build_cost_m2}


def _missing(lot: Lot, names: list[str]) -> list[str]:
    return [n for n in names if getattr(lot, n) is None]


def _base(lot: Lot, **o) -> Deal:
    rate = lot.mortgage_rate or 0.0
    d = Deal(price=lot.value, buy_costs=0.0, renovation=0.0, value_after=lot.value, lease_up_months=lot.lease_up_months,
             build_cost=0.0, build_months=0, building_life_years=lot.building_life_years, loan=0.0,
             teaser_rate=lot.teaser_rate if lot.teaser_rate is not None else rate,
             teaser_years=lot.teaser_years if lot.teaser_rate is not None else 0, float_rate=rate, grace_months=0,
             term_years=lot.term_years, rent=0.0, rent_growth=lot.rent_growth or 0.0, ramp_months=0,
             vacancy=lot.vacancy, management=lot.management, cogs=0.0, staff=0.0, running_costs=0.0,
             cost_growth=lot.cost_growth, rent_tax=lot.rent_tax, price_growth=lot.price_growth or 0.0,
             hold_years=lot.hold_years, sell_costs=lot.sell_costs, hurdle=lot.hurdle or 0.0, dscr_min=lot.dscr_min)
    return replace(d, **o)


_COMMON = ["price_growth", "hurdle"]
_BUILD = ["buildable_ratio", "max_floors", "build_cost_m2", "unit_size_m2", "fit_out_per_unit",
          "running_cost_per_unit", "rent_growth", "build_ltv"]


def _build_deal(lot: Lot, name: str, floors: int, shop: bool, need: list[str], loan: bool = True):
    need = _COMMON + _BUILD + need
    if loan and lot.build_ltv:
        need = need + ["mortgage_rate"]
    miss = _missing(lot, need)
    if miss:
        return Insufficient(f"option:{name}", "missing: " + ", ".join(miss)), None
    lay = layout(lot, floors, shop)
    if isinstance(lay, Insufficient):
        return Insufficient(f"option:{name}", lay.reason), None
    if lay["units"] < 1:
        return Insufficient(f"option:{name}", f"layout fits no unit of {lot.unit_size_m2} m²", lay), None
    d = _base(lot, build_cost=lay["build_cost"], build_months=lot.build_months,
              renovation=lay["units"] * lot.fit_out_per_unit, running_costs=lay["units"] * lot.running_cost_per_unit,
              loan=lay["build_cost"] * lot.build_ltv if loan else 0.0)
    return d, lay


def _options(lot: Lot) -> tuple[dict, dict]:
    deals: dict = {}
    meta: dict = {}
    miss = _missing(lot, _COMMON)
    deals["idle"] = (Insufficient("option:idle", "missing: " + ", ".join(miss)) if miss else
                     _base(lot, management=0.0, rent_tax=0.0, building_life_years=0, lease_up_months=0,
                           running_costs=lot.idle_holding_cost))
    miss = _missing(lot, _COMMON + ["land_lease_rent", "rent_growth"])
    deals["lease_land"] = (Insufficient("option:lease_land", "missing: " + ", ".join(miss)) if miss else
                           _base(lot, rent=lot.land_lease_rent, management=0.0, building_life_years=0, lease_up_months=1,
                                 running_costs=lot.idle_holding_cost))
    mf = lot.max_floors

    d, lay = _build_deal(lot, "build_studios", mf or 0, False, ["unit_rent"])
    if lay:
        d = replace(d, rent=lay["units"] * lot.unit_rent)
    deals["build_studios"], meta["build_studios"] = d, lay

    d, lay = _build_deal(lot, "build_shop_studios", mf or 0, True, ["unit_rent", "shop_rent"])
    if lay:
        d = replace(d, rent=lot.shop_rent + lay["units"] * lot.unit_rent, running_costs=(lay["units"] + 1) * lot.running_cost_per_unit)
    deals["build_shop_studios"], meta["build_shop_studios"] = d, lay

    if mf is not None and mf < 2:
        deals["build_small"], meta["build_small"] = Insufficient("option:build_small", f"max_floors {mf} leaves no smaller build"), None
    else:
        d, lay = _build_deal(lot, "build_small", (mf or 1) - 1, False, ["unit_rent"])
        if lay:
            d = replace(d, rent=lay["units"] * lot.unit_rent, build_months=max(1, lot.build_months - 1))
        deals["build_small"], meta["build_small"] = d, lay

    d, lay = _build_deal(lot, "chdv", mf or 0, False, ["chdv_unit_rate", "chdv_occ", "chdv_staff"])
    if lay:
        d = replace(d, rent=lay["units"] * lot.chdv_unit_rate * lot.chdv_occ, vacancy=0.0, ramp_months=lot.ramp_months,
                    management=lot.chdv_management, cogs=lot.chdv_cogs, staff=lot.chdv_staff, rent_tax=lot.business_tax)
    deals["chdv"], meta["chdv"] = d, lay

    d, lay = _build_deal(lot, "homestay", mf or 0, False, ["homestay_adr", "homestay_occ", "homestay_staff"])
    if lay:
        rooms = lot.homestay_rooms if lot.homestay_rooms is not None else lay["units"]
        lay = dict(lay, rooms=rooms)
        d = replace(d, rent=rooms * lot.homestay_adr * DAYS_PER_MONTH * lot.homestay_occ, vacancy=0.0,
                    ramp_months=lot.ramp_months, management=lot.homestay_management, cogs=lot.homestay_cogs,
                    staff=lot.homestay_staff, rent_tax=lot.business_tax)
    deals["homestay"], meta["homestay"] = d, lay

    need_jv = ["unit_rent"]
    d, lay = _build_deal(lot, "jv", mf or 0, False, need_jv, loan=False)
    if lay:
        d = replace(d, rent=lay["units"] * lot.unit_rent, loan=0.0)
        share = lot.jv_owner_share
        basis = "given"
        if share is None:
            share = lot.value / (lot.value + d.build_cost + d.renovation)
            basis = "land's share of land + build + fit-out"
        lay = dict(lay, owner_share=share, share_basis=basis)
    deals["jv"], meta["jv"] = d, lay

    miss = _missing(lot, ["deposit_rate", "hurdle"])
    if miss:
        deals["sell_deposit"] = Insufficient("option:sell_deposit", "missing: " + ", ".join(miss))
    else:
        net = lot.value * (1 - lot.sell_costs)
        deals["sell_deposit"] = _base(lot, price=net, value_after=net, renovation=lot.value * lot.sell_costs,
                                      rent=net * lot.deposit_rate / 12, vacancy=0.0, management=0.0, rent_tax=0.0,
                                      lease_up_months=0, building_life_years=0, price_growth=0.0, rent_growth=0.0,
                                      sell_costs=0.0)
        meta["sell_deposit"] = {"proceeds": net, "note": "deposit interest of individuals is PIT-exempt"}

    miss = _missing(lot, ["hurdle", "rental_yield_gross", "rental_price_growth", "rental_running_rate", "rent_growth"])
    if miss:
        deals["sell_buy_rental"] = Insufficient("option:sell_buy_rental", "missing: " + ", ".join(miss))
    else:
        net = lot.value * (1 - lot.sell_costs)
        p = net / (1 + lot.rental_buy_costs)
        deals["sell_buy_rental"] = _base(lot, price=p, value_after=p, buy_costs=lot.rental_buy_costs,
                                         renovation=lot.value * lot.sell_costs, rent=p * lot.rental_yield_gross / 12,
                                         running_costs=p * lot.rental_running_rate / 12, vacancy=lot.rental_vacancy,
                                         lease_up_months=1, building_life_years=0, price_growth=lot.rental_price_growth)
        meta["sell_buy_rental"] = {"proceeds": net, "rental_price": p}
    return deals, meta


def options(lot: Lot) -> dict[str, Deal | Insufficient]:
    """Every option as a Deal (or Insufficient naming the missing inputs), keyed by :data:`OPTION_NAMES`. The ``jv``
    Deal is the whole project without a loan; the landowner's slice is :func:`jv_owner`."""
    return _options(lot)[0]


def jv_owner(d: Deal, land_value: float, share: float) -> dict:
    """The landowner's economics in a JV: contributes the land (outflow ``land_value`` today), receives ``share`` of
    each month's NOI and of the net sale. Builder funds the build. Returns irr (annual), npv at ``d.hurdle``,
    profit (VND), and the monthly flows. Assumes the sale proceeds — land included — are split by ``share``; a real
    BCC contract may return the land to its owner instead, which this does not model."""
    rows = _schedule(d)[1:]
    flows = [-land_value] + [share * r["noi"] for r in rows]
    flows[-1] += share * rows[-1]["value"] * (1 - d.sell_costs)
    mh = (1 + d.hurdle) ** (1 / 12) - 1
    return {"share": share, "irr": irr_monthly(flows), "npv": sum(c / (1 + mh) ** t for t, c in enumerate(flows)),
            "profit": sum(flows), "flows": flows}


def _irr_of(name: str, d: Deal, lot: Lot, meta: dict) -> float | None:
    if name == "jv":
        return jv_owner(d, lot.value, meta["jv"]["owner_share"])["irr"]
    return analyse(d)["irr"]


def break_even_rent(lot: Lot, name: str, lo: float = 0.0, hi: float = 10.0, iters: int = 36) -> dict | Insufficient:
    """The income at which option ``name`` earns exactly ``lot.hurdle`` (equity IRR; the owner's IRR for ``jv``),
    found by bisection on a multiplier of the option's monthly income in ``[lo, hi]``. Returns the multiplier, the
    monthly income (VND) and, for build options, the income per unit. Insufficient when the option itself is, when
    it has no income to scale, or when no multiplier in range clears the hurdle. A multiplier of ``lo`` means the
    hurdle is already met without that much income (the land's growth carries it)."""
    deals, meta = _options(lot)
    d = deals.get(name)
    if d is None:
        raise ValueError(f"unknown option {name!r}")
    if isinstance(d, Insufficient):
        return Insufficient("break_even_rent", f"{name}: {d.reason}")
    if d.rent <= 0:
        return Insufficient("break_even_rent", f"{name} has no income to scale")
    h = lot.hurdle

    def ok(m: float) -> bool:
        irr = _irr_of(name, replace(d, rent=d.rent * m), lot, meta)
        return irr is not None and irr >= h
    if not ok(hi):
        return Insufficient("break_even_rent", f"{name}: no income up to {hi}× today's clears the {h:.1%} hurdle",
                            {"hi": hi})
    if ok(lo):
        m = lo
    else:
        a, b = lo, hi
        for _ in range(iters):
            mid = (a + b) / 2
            if ok(mid):
                b = mid
            else:
                a = mid
        m = b
    out = {"option": name, "hurdle": h, "multiplier": m, "rent": d.rent * m, "current_rent": d.rent}
    lay = meta.get(name)
    if lay and lay.get("units"):
        out["per_unit"] = d.rent * m / (lay.get("rooms") or lay["units"])
        out["units"] = lay.get("rooms") or lay["units"]
    return out


def evaluate(lot: Lot) -> dict:
    """Analyse every option, solve each one's break-even income, and rank. Returns ``options`` (per option: the
    key numbers, or the Insufficient), ``ranking`` (eligible options by IRR, best first: IRR defined and DSCR ≥
    ``dscr_min`` or no debt), ``excluded`` with the reason, and ``recommendation`` with reasons built from the numbers.
    For ``jv`` the IRR/NPV/profit are the landowner's; ``extra_cash`` is own money beyond the land (VND)."""
    deals, meta = _options(lot)
    table: dict = {}
    for name in OPTION_NAMES:
        d = deals[name]
        if isinstance(d, Insufficient):
            table[name] = {"insufficient": d.reason}
            continue
        a = analyse(d)
        row = {"irr": a["irr"], "npv": a["npv"], "profit": a["profit"], "cash_in": a["cash_in"],
               "extra_cash": max(0.0, a["cash_in"] - lot.value), "peak_cash_out": a["peak_cash_out"],
               "stable_cash": a["stable"]["cash"], "dscr": a["stable"]["dscr"], "yield_on_cost": a["yield_on_cost"],
               "rent": d.rent, "loan": a["loan_used"], "passes": a["passes"], "layout": meta.get(name)}
        if name == "jv":
            o = jv_owner(d, lot.value, meta["jv"]["owner_share"])
            row.update(irr=o["irr"], npv=o["npv"], profit=o["profit"], extra_cash=0.0,
                       stable_cash=a["stable"]["cash"] * o["share"], owner_share=o["share"], project_irr=a["irr"])
        be = break_even_rent(lot, name) if d.rent > 0 else None
        row["break_even"] = None if be is None else (be if isinstance(be, dict) else {"insufficient": be.reason})
        table[name] = row
    eligible, excluded = [], {}
    for name, r in table.items():
        if "insufficient" in r:
            excluded[name] = "insufficient inputs: " + r["insufficient"]
        elif r["irr"] is None:
            excluded[name] = "IRR undefined (no sign change in the cash flows)"
        elif r["dscr"] is not None and r["dscr"] < lot.dscr_min:
            excluded[name] = f"DSCR {r['dscr']:.2f} below {lot.dscr_min}"
        else:
            eligible.append(name)
    eligible.sort(key=lambda k: table[k]["irr"], reverse=True)
    rec = None
    if eligible:
        best = eligible[0]
        b = table[best]
        reasons = [f"{best}: equity IRR {b['irr']:.1%} vs hurdle {lot.hurdle:.1%} "
                   f"({'clears' if b['irr'] >= lot.hurdle else 'misses'} it)"]
        for ref in ("idle", "sell_deposit"):
            if ref != best and ref in table and table[ref].get("irr") is not None:
                reasons.append(f"{(b['irr'] - table[ref]['irr']) * 100:+.1f} points vs {ref} ({table[ref]['irr']:.1%})")
        if b["extra_cash"] > 0:
            reasons.append(f"needs {b['extra_cash']:,.0f} VND of own money beyond the land; peak cash out {b['peak_cash_out']:,.0f}")
        if b["dscr"] is not None:
            reasons.append(f"stabilised DSCR {b['dscr']:.2f}")
        if len(eligible) > 1:
            s = table[eligible[1]]
            reasons.append(f"runner-up {eligible[1]} at {s['irr']:.1%}")
        if b.get("break_even") and "multiplier" in b["break_even"]:
            m = b["break_even"]["multiplier"]
            reasons.append(f"income could fall to {m:.0%} of today's before missing the hurdle" if m <= 1 else
                           f"income would have to reach {m:.0%} of today's to clear the hurdle")
        rec = {"option": best, "clears_hurdle": b["irr"] >= lot.hurdle, "reasons": reasons}
    return {"options": table, "ranking": eligible, "excluded": excluded, "recommendation": rec,
            "land_value": lot.value, "hurdle": lot.hurdle}
