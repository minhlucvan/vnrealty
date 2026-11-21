"""Named pricing metrics per property type — what the desk looks at to decide whether a listing is cheap.

Every function takes a ``listing`` (a dict as returned by :func:`vnrealty.pricing.peers.snapshot`: listing columns
plus ``price`` (VND; VND/month for rentals), ``seen_at``, ``days_on_market``, ``cuts``…) and a ``ctx`` (see
:func:`make_ctx`) and returns ``{metric_name: entry}``. An entry is either::

    {"value": float|str, "unit": str, "basis": str, "peer": {...}?, "ratio": float?, "independent": bool?}
    {"insufficient": reason}

* ``peer`` — :func:`vnrealty.pricing.peers.peer_stats` summary (scope, n, median, p25, p75, percentile, z) or
  ``{"insufficient": reason}``.
* ``ratio`` — the metric over its benchmark, oriented so the scorer knows what "good" is (see
  :mod:`vnrealty.pricing.score`).
* ``independent: False`` — the number was derived from peer medians in a way that only restates the price-per-unit
  percentile (e.g. a yield from the ward's median rent); it is shown but not scored, to avoid double counting.

Per type: :func:`land`, :func:`house` (also villa), :func:`apartment`, :func:`shophouse`, :func:`rooms` (chdv /
room / homestay), :func:`rental`; :func:`common` adds hedonic residual, value gap vs a triangulated value, days on
market, price cuts, negotiability, legal status and alley width to all. :func:`evaluate` dispatches on type.

**Missing inputs are never defaulted**: no rent → yields Insufficient; no age → depreciated building value
Insufficient; no ADR/occupancy → homestay income value Insufficient. Parameters (build cost, cap rates, margins…)
come from ``reference/pricing_params.json`` with their basis; the asking→sale haircut from
``reference/market_params.json`` is applied explicitly wherever a peer *asking* level becomes a *value*.
Money VND, area m², rates annual fractions, rents per month.
"""
from __future__ import annotations

import math
import re
import sqlite3
from typing import Any

from vnrealty.listings.parse import fold
from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation import comps as vcomps
from vnrealty.valuation import hedonic as vhedonic
from vnrealty.valuation import official as vofficial

from . import zoning
from .peers import UNITS, PeerCache, peer_stats, project_key, rooms_of, unit_value

__all__ = ["make_ctx", "ok", "na", "land", "house", "apartment", "shophouse", "rooms", "rental", "common",
           "evaluate", "KEY_METRIC", "operating_mode"]

# the metric that prices each type (used by the screen and the 'too cheap' flag)
KEY_METRIC = {"land": "price_m2", "house": "price_m2", "villa": "price_m2", "other": "price_m2",
              "apartment": "price_m2_floor", "shophouse": "price_per_frontage_m", "chdv": "price_per_room",
              "room": "price_per_room", "rent": "rent_m2"}


def make_ctx(con: sqlite3.Connection | None = None, as_of: str | None = None, **kw: Any) -> dict:
    """Build a metrics context.

    Keys (all optional except ``con``/``as_of`` for peer-based metrics): ``params`` (pricing params),
    ``market_params`` (comps params, for the haircut), ``cache`` (a shared :class:`PeerCache`), ``months`` (12),
    ``min_n`` (8), ``area_band`` (None), ``hedonic`` (a fitted :class:`~vnrealty.valuation.hedonic.HedonicModel`),
    ``valuation`` (an :class:`~vnrealty.types.Estimate` of this listing, e.g. triangulated), and listing-specific
    assumptions: ``rent`` (VND/month), ``studio_rent`` and ``room_rent`` (VND/month per unit), ``adr`` (VND per
    room-night), ``occupancy`` (fraction), ``rooms``, ``operating_mode`` ('homestay' | 'chdv'), ``road_width_m``,
    ``build_level`` ('basic' | 'standard' | 'premium'), ``age_years``, ``official_price_m2`` (VND/m²).
    """
    ctx = {"con": con, "as_of": as_of, "months": 12, "min_n": 8, "area_band": None}
    ctx.update(kw)
    if ctx.get("params") is None:
        ctx["params"] = zoning.load_params()
    if ctx.get("market_params") is None:
        ctx["market_params"] = vcomps.load_params()
    if ctx.get("cache") is None and con is not None and as_of:
        ctx["cache"] = PeerCache(con, as_of, ctx["months"], ctx["params"])
    return ctx


def ok(value: Any, unit: str, basis: str, **kw: Any) -> dict:
    """A computed metric entry."""
    d = {"value": value, "unit": unit, "basis": basis}
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


def na(reason: str) -> dict:
    """An Insufficient metric entry."""
    return {"insufficient": reason}


def _is_na(x) -> bool:
    return isinstance(x, Insufficient) or (isinstance(x, dict) and "insufficient" in x)


def _ps(listing: dict, ctx: dict, unit: str, **kw) -> dict | Insufficient:
    con, as_of = ctx.get("con"), ctx.get("as_of")
    if con is None or not as_of:
        return Insufficient("peers", "no database/as_of in ctx")
    return peer_stats(con, listing, as_of, months=ctx["months"], min_n=ctx["min_n"],
                      area_band=kw.pop("area_band", ctx.get("area_band")), unit=unit, cache=ctx.get("cache"), **kw)


def _peer_summary(ps: dict | Insufficient) -> dict:
    if isinstance(ps, Insufficient):
        return {"insufficient": ps.reason}
    return {k: ps[k] for k in ("scope", "place", "n", "median", "p25", "p75", "percentile", "z")}


def _unit_metric(listing: dict, ctx: dict, unit: str, basis: str, **peer_kw) -> dict:
    v = unit_value(listing, unit, ctx["params"])
    if v is None:
        return na(f"cannot compute {UNITS[unit]}: price or the {unit} denominator is missing")
    return ok(v, UNITS[unit], basis, peer=_peer_summary(_ps(listing, ctx, unit, **peer_kw)))


def _haircut(ctx: dict) -> float:
    return float(ctx["market_params"]["asking_to_sale"]["value"])


def _no_price(listing: dict) -> str | None:
    if not listing.get("price") or listing["price"] <= 0:
        return "no price (negotiable / not stated)"
    return None


def _build_cost_m2(ctx: dict) -> tuple[float, str]:
    bc = ctx["params"]["build_cost_m2"]
    lvl = ctx.get("build_level") or bc["default_level"]
    return float(bc[lvl]), f"build cost {lvl} {bc[lvl]:,.0f} VND/m² ({bc['basis_kind']})"


# ------------------------------------------------------------------ shared building blocks

def _land_value(listing: dict, ctx: dict, alley_override: float | None = None) -> tuple[float, str] | Insufficient:
    """Sale-equivalent value (VND) of the listing's land: adjusted land comps (valuation.comps), else land peers'
    median price/m² × area × the asking→sale haircut."""
    area = listing.get("area_m2")
    if not area:
        return Insufficient("land_value", "land area unknown")
    con, as_of = ctx.get("con"), ctx.get("as_of")
    if con is None or not as_of:
        return Insufficient("land_value", "no database/as_of in ctx")
    subj = {k: listing.get(k) for k in ("ward_code", "lat", "lng", "area_m2", "frontage_m", "alley_m", "corner", "legal")}
    subj["ptype"] = "land"
    if alley_override is not None:
        subj["alley_m"] = alley_override
    est = vcomps.value_by_comps(con, subj, as_of, params=ctx["market_params"], min_n=5)
    if isinstance(est, Estimate):
        return est.value, f"land comps (valuation.comps, n={est.n}, sale-equivalent)"
    ps = _ps({**subj, "id": listing.get("id"), "price": None, "deal": "sale"}, ctx, "price_m2", ptype="land")
    if isinstance(ps, Insufficient):
        return Insufficient("land_value", f"comps: {est.reason}; peers: {ps.reason}")
    hc = _haircut(ctx)
    return ps["median"] * area * hc, (f"land peers median {ps['median']:,.0f} VND/m² ({ps['scope']}, n={ps['n']}) × "
                                      f"{area:g} m² × haircut {hc}")


def _rent(listing: dict, ctx: dict, area: float | None) -> tuple[float, str, bool] | Insufficient:
    """Monthly rent (VND): ``ctx['rent']`` (listing-specific, independent) or rent peers' median rent/m² × area
    (not independent: restates the peer level)."""
    if ctx.get("rent"):
        return float(ctx["rent"]), "rent given for this listing", True
    if not area:
        return Insufficient("rent", "no listing rent and area unknown")
    ps = _ps({**listing, "price": None}, ctx, "rent_m2", deal="rent")
    if isinstance(ps, Insufficient):
        return Insufficient("rent", f"no listing rent; rent peers: {ps.reason}")
    return ps["median"] * area, (f"rent peers median {ps['median']:,.0f} VND/m²/month ({ps['scope']}, n={ps['n']}) "
                                 f"× {area:g} m² (asking rents)"), False


def _ward_yield(listing: dict, ctx: dict) -> tuple[float, str] | Insufficient:
    """Ward benchmark gross yield = median rent/m²·12 ÷ median asking price/m² of the same type (both peers)."""
    base = {**listing, "price": None}
    r = _ps(base, ctx, "rent_m2", deal="rent")
    s = _ps(base, ctx, "price_m2", deal="sale")
    if isinstance(r, Insufficient) or isinstance(s, Insufficient):
        return Insufficient("ward_yield", "; ".join(x.reason for x in (r, s) if isinstance(x, Insufficient)))
    return r["median"] * 12 / s["median"], f"rent peers ({r['scope']}, n={r['n']}) / sale peers ({s['scope']}, n={s['n']})"


def _yield_metrics(listing: dict, ctx: dict, area: float | None, out: dict) -> tuple[float, bool] | None:
    """Adds gross_yield and gross_yield_vs_ward; returns (annual rent, independent) or None."""
    price = listing["price"]
    rt = _rent(listing, ctx, area)
    if isinstance(rt, Insufficient):
        out["gross_yield"] = na(rt.reason)
        out["gross_yield_vs_ward"] = na(rt.reason)
        return None
    rent, basis, indep = rt
    gy = rent * 12 / price
    out["gross_yield"] = ok(gy, "fraction/yr", f"{basis}; ×12 ÷ asking", independent=indep)
    if not indep:
        out["gross_yield_vs_ward"] = na("needs a listing-specific rent (ctx['rent']); with the ward's median rent it "
                                        "would only restate price/m²")
    else:
        wy = _ward_yield(listing, ctx)
        out["gross_yield_vs_ward"] = (na(wy.reason) if isinstance(wy, Insufficient) else
                                      ok(gy, "fraction/yr", f"listing yield vs ward median yield {wy[0]:.4f} ({wy[1]})",
                                         ratio=gy / wy[0], benchmark=wy[0]))
    return rent * 12, indep


# ------------------------------------------------------------------ per type

def land(listing: dict, ctx: dict) -> dict:
    """Land: price/m²; price per buildable m² (GFA from zoning); land residual value of the best simple build vs
    asking (the key 'is the land cheap' metric); price per frontage metre; official-table ratio.

    Residual (VND) = GDV − build cost − soft cost − developer margin × GDV − finance, where GDV = max(sale value of a
    new house = house peers' median price/m² floor × GFA × haircut, studio income value = units × studio rent × 12 ×
    (1 − vacancy) × (1 − opex) ÷ cap rate); build cost = GFA × build cost/m²; finance = (build + soft) × rate ×
    (½ build_months + sale_months) / 12. ``residual_vs_asking`` = residual ÷ asking (residual is sale-equivalent;
    asking is asking — read ≥ 1 as cheap, ≥ 1/haircut as cheap even after negotiation). House peers are taken on the
    ward ladder without an access adjustment (street vs kiệt), so the sale route is coarse; both routes are kept in
    ``residual_value.parts.gdv_options``. A street lot of unknown carriageway uses the lower-bound floor count, so
    its residual errs low (``bound='lower'``).
    """
    out: dict[str, dict] = {}
    p = ctx["params"]
    if (why := _no_price(listing)):
        for k in ("price_m2", "price_per_buildable_m2", "residual_vs_asking", "price_per_frontage_m", "official_ratio"):
            out[k] = na(why)
        return out
    price, area = listing["price"], listing.get("area_m2")
    out["price_m2"] = _unit_metric(listing, ctx, "price_m2", "asking ÷ land area", ptype=listing.get("ptype") or "land")
    g = zoning.gfa(area, listing.get("alley_m"), ctx.get("road_width_m"), p)
    if isinstance(g, Insufficient):
        out["gfa_m2"] = na(g.reason)
        out["price_per_buildable_m2"] = na(g.reason)
        out["residual_vs_asking"] = na(g.reason)
    else:
        out["gfa_m2"] = ok(g["gfa_m2"], "m²", g["basis"], bound=g["bound"])
        out["price_per_buildable_m2"] = _unit_metric({**listing, "road_width_m": ctx.get("road_width_m")}, ctx,
                                                     "price_per_buildable_m2", "asking ÷ zoning GFA; " + g["basis"])
        out.update(_residual(listing, ctx, g))
    out["price_per_frontage_m"] = _unit_metric(listing, ctx, "price_per_frontage_m", "asking ÷ frontage")
    out["official_ratio"] = _official_ratio(listing, ctx)
    return out


def _residual(listing: dict, ctx: dict, g: dict) -> dict:
    p = ctx["params"]
    out: dict[str, dict] = {}
    gfa = g["gfa_m2"]
    hc = _haircut(ctx)
    gdvs: dict[str, tuple[float, str]] = {}
    why: list[str] = []
    hp = _ps({**listing, "price": None}, ctx, "price_m2_floor", ptype="house")
    if isinstance(hp, Insufficient):
        why.append("house-sale GDV: " + hp.reason)
    else:
        gdvs["sell_house"] = (hp["median"] * gfa * hc, f"house peers median {hp['median']:,.0f} VND/m² floor "
                                                       f"({hp['scope']}, n={hp['n']}) × {gfa:.0f} m² × haircut {hc}")
    st = p["studio"]
    units = math.floor(gfa * st["efficiency"] / st["unit_size_m2"])
    srent, sbasis = None, None
    if ctx.get("studio_rent"):
        srent, sbasis = float(ctx["studio_rent"]), "studio rent given"
    else:
        rp = _ps({**listing, "price": None, "ptype": "room"}, ctx, "rent_month", deal="rent", ptype="room")
        if isinstance(rp, Insufficient):
            why.append("studio GDV: " + rp.reason)
        else:
            srent, sbasis = rp["median"], f"room rent peers median ({rp['scope']}, n={rp['n']})"
    if srent is not None and units > 0:
        noi = units * srent * 12 * (1 - st["vacancy"]) * (1 - st["opex_share"])
        cap = p["cap_rate"]["studio_build"]
        gdvs["build_studios"] = (noi / cap, f"{units} studios × {srent:,.0f} VND/month ({sbasis}) × 12 × (1 − "
                                            f"{st['vacancy']}) × (1 − {st['opex_share']}) ÷ cap {cap}")
    if not gdvs:
        out["residual_vs_asking"] = na("no GDV: " + "; ".join(why))
        return out
    best = max(gdvs, key=lambda k: gdvs[k][0])
    gdv = gdvs[best][0]
    bcm2, bcb = _build_cost_m2(ctx)
    build = gfa * bcm2
    soft = build * p["soft_cost_share"]["value"]
    margin = gdv * p["developer_margin"]["value"]
    months = 0.5 * p["build_months"]["value"] + p["sale_months"]["value"]
    fin = (build + soft) * p["finance_rate"]["value"] * months / 12
    resid = gdv - build - soft - margin - fin
    parts = {"gdv": gdv, "gdv_route": best, "gdv_options": {k: v[0] for k, v in gdvs.items()}, "build": build,
             "soft": soft, "margin": margin, "finance": fin}
    out["gdv"] = ok(gdv, "VND", gdvs[best][1], route=best)
    out["residual_value"] = ok(resid, "VND", f"GDV − build ({bcb}) − soft − margin − finance", parts=parts,
                               bound="lower" if g["bound"] == "lower" else None)
    r = resid / listing["price"]
    out["residual_vs_asking"] = ok(r, "×", "residual value ÷ asking (≥1: land priced at or below what a build "
                                           "supports)", ratio=r, bound="lower" if g["bound"] == "lower" else None)
    return out


def _official_ratio(listing: dict, ctx: dict) -> dict:
    area = listing.get("area_m2")
    if not area:
        return na("land area unknown")
    off = ctx.get("official_price_m2")
    basis = "official price given"
    if not off:
        if listing.get("alley_m") != 0 or not listing.get("street"):
            return na("official table: only street-front (VT1) rows are sourced; needs alley_m = 0 and a street")
        off = vofficial.lookup(listing["street"], 1)
        if isinstance(off, Insufficient):
            return na(off.reason)
        basis = f"official VT1 price for {listing['street']}"
    r = listing["price"] / area / off
    return ok(r, "×", f"asking/m² ÷ {basis} ({off:,.0f} VND/m²); high is normal, < 1 is a flag worth checking",
              official_price_m2=off)


def house(listing: dict, ctx: dict) -> dict:
    """House / villa: price/m² land and floor vs peers; cost approach = land value + depreciated replacement cost
    of the building (floor area × build cost × (1 − age/life)) vs asking; implied building value = asking − land
    value; gross yield (listing rent or rent peers)."""
    out: dict[str, dict] = {}
    if (why := _no_price(listing)):
        for k in ("price_m2", "price_m2_floor", "cost_value_vs_asking", "gross_yield", "gross_yield_vs_ward"):
            out[k] = na(why)
        return out
    p = ctx["params"]
    price = listing["price"]
    out["price_m2"] = _unit_metric(listing, ctx, "price_m2", "asking ÷ land area")
    out["price_m2_floor"] = _unit_metric(listing, ctx, "price_m2_floor", "asking ÷ floor area")
    lv = _land_value(listing, ctx)
    if isinstance(lv, Insufficient):
        out["land_value"] = na(lv.reason)
        out["implied_building_value"] = na(lv.reason)
        out["cost_value_vs_asking"] = na("land value: " + lv.reason)
    else:
        out["land_value"] = ok(lv[0], "VND", lv[1])
        ib = price - lv[0]
        out["implied_building_value"] = ok(ib, "VND", "asking − land value" +
                                           (" (negative: asking below land value)" if ib < 0 else ""))
        fa = zoning.floor_area(listing, p)
        if fa is None:
            out["building_cost_ratio"] = na("floor area unknown (needs floor area, or land area and floors)")
        else:
            bcm2, bcb = _build_cost_m2(ctx)
            new_cost = fa[0] * bcm2
            r = ib / new_cost
            out["building_cost_ratio"] = ok(r, "×", f"(asking − land value) ÷ (floor area {fa[0]:,.0f} m²"
                                            f"{' estimated: land × floors × max coverage' if fa[1] else ''} × {bcb}); "
                                            "below 1 = paying less for the building than building it new",
                                            ratio=r, floor_area_estimated=fa[1])
        bld = _building_value(listing, ctx)
        if isinstance(bld, Insufficient):
            out["building_value"] = na(bld.reason)
            out["cost_value_vs_asking"] = na("building value: " + bld.reason)
        else:
            out["building_value"] = ok(bld[0], "VND", bld[1])
            cv = lv[0] + bld[0]
            out["cost_value_vs_asking"] = ok(cv / price, "×", f"(land {lv[0]:,.0f} + building {bld[0]:,.0f}) ÷ asking",
                                             ratio=cv / price, cost_value=cv)
    _yield_metrics(listing, ctx, listing.get("area_m2"), out)
    return out


def _age(listing: dict, ctx: dict) -> float | None:
    if ctx.get("age_years") is not None:
        return float(ctx["age_years"])
    ex = listing.get("extra")
    if isinstance(ex, str):
        import json
        try:
            ex = json.loads(ex)
        except ValueError:
            ex = None
    if isinstance(ex, dict):
        if isinstance(ex.get("age_years"), (int, float)):
            return float(ex["age_years"])
        yb = ex.get("year_built")
        if isinstance(yb, (int, float)) and ctx.get("as_of"):
            return max(0.0, int(ctx["as_of"][:4]) - yb)
    return None


def _building_value(listing: dict, ctx: dict) -> tuple[float, str] | Insufficient:
    fa = listing.get("floor_area_m2")
    if not fa:
        return Insufficient("building_value", "floor area unknown")
    age = _age(listing, ctx)
    if age is None:
        return Insufficient("building_value", "building age unknown (ctx age_years or extra.year_built)")
    life = ctx["params"]["building_life_years"].get(listing.get("ptype") or "house")
    if life is None:
        return Insufficient("building_value", f"no building life for {listing.get('ptype')}")
    bcm2, bcb = _build_cost_m2(ctx)
    dep = max(0.0, 1 - age / life)
    return fa * bcm2 * dep, f"{fa:g} m² × {bcb} × (1 − {age:g}/{life})"


def apartment(listing: dict, ctx: dict) -> dict:
    """Apartment: price/m² floor vs peers of the same matched project (else ward ladder); price-to-annual-rent
    multiple vs the ward's; gross and net yield (net = (rent·12·(1 − rent tax) − mgmt fee/m²·area·12) ÷ asking) vs the
    apartment cap rate; legal (sổ hồng vs HĐMB)."""
    out: dict[str, dict] = {}
    p = ctx["params"]
    leg = listing.get("legal")
    out["legal"] = ok(leg or "unknown", "status", "so_hong/so_do = certificate; hdmb = sale contract only (no pink "
                                                  "book yet)")
    if (why := _no_price(listing)):
        for k in ("price_m2_floor", "price_to_rent", "gross_yield", "net_yield", "gross_yield_vs_ward"):
            out[k] = na(why)
        return out
    price = listing["price"]
    area = listing.get("floor_area_m2") or listing.get("area_m2")
    proj = project_key(listing.get("title"), listing.get("address"))
    m = _unit_metric(listing, ctx, "price_m2_floor", "asking ÷ floor area", project=proj,
                     project_min_n=int(p["project_min_n"]["value"]))
    if proj and "value" in m:
        m["project"] = proj
    out["price_m2_floor"] = m
    ys = _yield_metrics(listing, ctx, area, out)
    if ys is None:
        out["price_to_rent"] = out["net_yield"] = na(out["gross_yield"]["insufficient"])
        return out
    annual, indep = ys
    mult = price / annual
    wy = _ward_yield(listing, ctx)
    if isinstance(wy, Insufficient):
        out["price_to_rent"] = ok(mult, "× annual rent", "asking ÷ (rent × 12); ward multiple: " + wy.reason,
                                  independent=indep)
    else:
        bench = 1 / wy[0]
        out["price_to_rent"] = ok(mult, "× annual rent", f"asking ÷ (rent × 12) vs ward multiple {bench:.1f}",
                                  ratio=mult / bench, benchmark=bench, independent=indep)
    fee = p["apartment_mgmt_fee_m2"]["value"]
    tax = p["rent_tax"]["value"]
    if not area:
        out["net_yield"] = na("floor area unknown (management fee)")
    else:
        ny = (annual * (1 - tax) - fee * area * 12) / price
        cap = p["cap_rate"]["apartment"]
        out["net_yield"] = ok(ny, "fraction/yr", f"(rent·12·(1 − {tax}) − {fee:,.0f} VND/m²/month × {area:g} m² × 12) "
                                                 f"÷ asking; vs cap rate {cap}", ratio=ny / cap, independent=indep)
    return out


def shophouse(listing: dict, ctx: dict) -> dict:
    """Shophouse: price per frontage metre and price/m² vs peers; rent per frontage metre; gross yield; price ÷
    land value (the premium paid for the frontage — information, not scored)."""
    out: dict[str, dict] = {}
    if (why := _no_price(listing)):
        for k in ("price_per_frontage_m", "price_m2", "gross_yield", "gross_yield_vs_ward", "price_to_land_value"):
            out[k] = na(why)
        return out
    out["price_per_frontage_m"] = _unit_metric(listing, ctx, "price_per_frontage_m", "asking ÷ frontage")
    out["price_m2"] = _unit_metric(listing, ctx, "price_m2", "asking ÷ land area")
    ys = _yield_metrics(listing, ctx, listing.get("area_m2"), out)
    f = listing.get("frontage_m")
    if ys is None or not f:
        out["rent_per_frontage_m"] = na("rent or frontage unknown")
    else:
        out["rent_per_frontage_m"] = ok(ys[0] / 12 / f, "VND/month per m frontage", "monthly rent ÷ frontage",
                                        independent=ys[1])
    lv = _land_value(listing, ctx, alley_override=listing.get("alley_m"))
    out["price_to_land_value"] = (na(lv.reason) if isinstance(lv, Insufficient) else
                                  ok(listing["price"] / lv[0], "×", "asking ÷ land value (" + lv[1] + ")"))
    return out


def operating_mode(listing: dict, ctx: dict) -> str:
    """'homestay' (rooms let by the night) or 'chdv' (rooms let by the month): ``ctx['operating_mode']``, else
    homestay when the title mentions homestay / khách sạn / nhà nghỉ, else chdv."""
    if ctx.get("operating_mode") in ("homestay", "chdv"):
        return ctx["operating_mode"]
    return "homestay" if re.search(r"homestay|khach san|nha nghi", fold(listing.get("title"))) else "chdv"


def rooms(listing: dict, ctx: dict) -> dict:
    """Homestay / CHDV / room building: price per room (key) vs peers; income-approach value = NOI ÷ cap rate vs
    asking; implied cap rate = NOI ÷ asking; revenue multiple = asking ÷ gross revenue (information).

    NOI homestay = rooms × ADR × occupancy × 365 × (1 − OTA fee) × (1 − opex share) — ADR and occupancy only from
    ctx. NOI CHDV = rooms × monthly rent × 12 × (1 − vacancy) × (1 − opex share), monthly rent from ctx or room rent
    peers (median monthly rent per room listing).
    """
    out: dict[str, dict] = {}
    p = ctx["params"]
    if (why := _no_price(listing)):
        for k in ("price_per_room", "income_value_vs_asking", "implied_cap_rate", "revenue_multiple"):
            out[k] = na(why)
        return out
    price = listing["price"]
    lst = dict(listing)
    if ctx.get("rooms"):
        lst["extra"] = {"rooms": ctx["rooms"]}
    out["price_per_room"] = _unit_metric(lst, ctx, "price_per_room", "asking ÷ rooms")
    n = rooms_of(lst)
    mode = operating_mode(listing, ctx)
    if not n:
        r = "room count unknown"
        out["income_value_vs_asking"] = out["implied_cap_rate"] = out["revenue_multiple"] = na(r)
        return out
    if mode == "homestay":
        adr, occ = ctx.get("adr"), ctx.get("occupancy")
        if not adr or not occ:
            r = "homestay needs ADR and occupancy (ctx adr, occupancy) — no published Đà Nẵng statistic to default to"
            out["income_value_vs_asking"] = out["implied_cap_rate"] = out["revenue_multiple"] = na(r)
            return out
        ota, opex = p["ota_fee_share"]["value"], p["opex_share"]["homestay"]
        rev = n * adr * occ * 365
        noi = rev * (1 - ota) * (1 - opex)
        cap = p["cap_rate"]["homestay"]
        basis = f"{n:g} rooms × ADR {adr:,.0f} × occ {occ} × 365 × (1 − OTA {ota}) × (1 − opex {opex})"
    else:
        rent, rb = ctx.get("room_rent"), "room rent given"
        if not rent:
            rp = _ps({**listing, "price": None}, ctx, "rent_month", deal="rent", ptype="room")
            if isinstance(rp, Insufficient):
                r = "CHDV needs a monthly room rent (ctx room_rent) or room rent peers: " + rp.reason
                out["income_value_vs_asking"] = out["implied_cap_rate"] = out["revenue_multiple"] = na(r)
                return out
            rent, rb = rp["median"], f"room rent peers median ({rp['scope']}, n={rp['n']})"
        vac, opex = p["chdv_vacancy"]["value"], p["opex_share"]["chdv"]
        rev = n * rent * 12 * (1 - vac)
        noi = rev * (1 - opex)
        cap = p["cap_rate"]["room" if listing.get("ptype") == "room" else "chdv"]
        basis = f"{n:g} rooms × {rent:,.0f} VND/month ({rb}) × 12 × (1 − vacancy {vac}) × (1 − opex {opex})"
    val = noi / cap
    out["noi"] = ok(noi, "VND/yr", basis, mode=mode)
    out["income_value_vs_asking"] = ok(val / price, "×", f"NOI ÷ cap {cap} ({p['cap_rate']['basis_kind']}) ÷ asking",
                                       ratio=val / price, income_value=val, mode=mode)
    out["implied_cap_rate"] = ok(noi / price, "fraction/yr", f"NOI ÷ asking vs cap rate {cap}", ratio=(noi / price) / cap)
    out["revenue_multiple"] = ok(price / rev, "× annual revenue", "asking ÷ gross revenue")
    return out


def rental(listing: dict, ctx: dict) -> dict:
    """A rental listing: rent/m² per month vs rent peers."""
    if (why := _no_price(listing)):
        return {"rent_m2": na(why)}
    return {"rent_m2": _unit_metric(listing, ctx, "rent_m2", "monthly rent ÷ area")}


def common(listing: dict, ctx: dict) -> dict:
    """For every type: hedonic residual (log; negative = below the model), value gap vs a triangulated value
    (value ÷ asking), days on market, price cuts, negotiability, legal status, alley width."""
    out: dict[str, dict] = {}
    model = ctx.get("hedonic")
    if model is None or isinstance(model, Insufficient):
        out["hedonic_residual"] = na("no fitted hedonic model in ctx" + (f": {model.reason}" if model else ""))
    elif not listing.get("price"):
        out["hedonic_residual"] = na("no price")
    else:
        r = vhedonic.residual(model, listing)
        out["hedonic_residual"] = (na(r.reason) if isinstance(r, Insufficient) else
                                   ok(r, "log", f"log(asking/m²) − hedonic prediction (n={model.n}, r²={model.r2:.2f}); "
                                                f"{math.exp(r) - 1:+.1%}"))
    v = ctx.get("valuation")
    if not isinstance(v, Estimate):
        out["value_gap"] = na("no triangulated valuation for this listing" + (f": {v.reason}" if isinstance(v, Insufficient) else ""))
    elif not listing.get("price"):
        out["value_gap"] = na("no price")
    else:
        out["value_gap"] = ok(v.value / listing["price"], "×", f"{v.method} value {v.value:,.0f} (sale-equivalent, as of "
                                                               f"{v.as_of}) ÷ asking", ratio=v.value / listing["price"])
    if listing.get("days_on_market") is None:
        out["days_on_market"] = na("no observation history")
        out["price_cuts"] = na("no observation history")
    else:
        out["days_on_market"] = ok(listing["days_on_market"], "days", f"as_of − first sighting {listing['first_obs']}")
        out["price_cuts"] = ok(listing.get("cuts", 0), "count", f"price decreases; latest vs earlier high "
                                                                f"{listing.get('cut_total', 0.0):+.1%}",
                               cut_total=listing.get("cut_total", 0.0))
    out["negotiable"] = ok(bool(listing.get("negotiable")), "bool", "an observation without a number (thỏa thuận)")
    out["legal_status"] = ok(listing.get("legal") or "unknown", "status", "as stated in the listing")
    a = listing.get("alley_m")
    out["alley_m"] = na("alley width unknown") if a is None else ok(a, "m", "0 = street frontage")
    return out


def evaluate(listing: dict, ctx: dict) -> dict:
    """All metrics for one listing: the type's own (dispatch on deal / ptype) plus :func:`common`."""
    if listing.get("deal") == "rent":
        own = rental(listing, ctx)
    else:
        t = listing.get("ptype")
        fn = {"land": land, "house": house, "villa": house, "apartment": apartment, "shophouse": shophouse,
              "chdv": rooms, "room": rooms}.get(t)
        if fn is None:
            own = {"price_m2": (na(_no_price(listing)) if _no_price(listing) else
                                _unit_metric(listing, ctx, "price_m2", "asking ÷ area"))}
        else:
            own = fn(listing, ctx)
    return {**own, **common(listing, ctx)}
