"""Compositions of library calls the CLI needs in several commands (value, project, score, screen, reports).

Every valuation, index, projection and deal number comes from a library function. Three small pieces of
arithmetic live here because no library exposes them yet — each is stated where it is defined and listed in the CLI
report as a library change to make:

* :func:`gap_to_ask` — (estimate − ask) / ask;
* :func:`drift_vol` — annualised mean and standard deviation of monthly log changes of an index;
* :func:`listing_yield` — 12 × ward median asking rent per m² ÷ the listing's asking price per m².
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import math
from pathlib import Path

from vnrealty.deal.engine import Deal
from vnrealty.types import Estimate, Insufficient

from .common import CliError, load_json

COMPS_RADIUS_KM = 3.0   # judgement: walkable-market radius for comps when the subject has coordinates

__all__ = ["run_value", "fit_hedonic", "index_series", "drift_vol", "gap_to_ask", "official_position", "official_floor",
           "load_deal", "deal_from_dict", "PRESETS", "preset_template", "listing_rows", "listing_yield",
           "days_before", "load_profile", "load_household", "sell_costs"]


# ------------------------------------------------------------------ valuation

def official_position(alley_m: float | None) -> int | None:
    """Official-table position class from access width (QĐ 46/2016 classes, as in reference/market_params.json):
    street frontage → 1, kiệt ≥ 4.5 m → 2, 3–4.5 m → 3, < 3 m → 4; None when the width is unknown."""
    if alley_m is None:
        return None
    if alley_m <= 0:
        return 1
    return 2 if alley_m >= 4.5 else 3 if alley_m >= 3 else 4


def official_floor(subject: dict) -> dict:
    """The official land-price table value (VND/m² and × area) — a floor and the tax basis, never a market value,
    so it is reported beside the triangulation, not inside it."""
    from vnrealty.valuation.official import lookup
    if not subject.get("street"):
        return {"status": "insufficient", "reason": "subject has no street name to look up"}
    pos = official_position(subject.get("alley_m"))
    if pos is None:
        return {"status": "insufficient", "reason": "access width unknown: position class cannot be set"}
    r = lookup(subject["street"], position=pos)
    if isinstance(r, Insufficient):
        return {"status": "insufficient", "reason": r.reason, "position": pos}
    out = {"status": "ok", "price_m2": r, "position": pos, "role": "floor and tax basis, not market value"}
    if subject.get("area_m2"):
        out["value"] = r * subject["area_m2"]
    return out


def gap_to_ask(estimate: float | None, ask: float | None) -> float | None:
    """(estimate − ask) / ask as a fraction; None when either is missing. Positive = asking below our value."""
    if estimate is None or not ask:
        return None
    return (estimate - ask) / ask


def index_series(con, as_of: str, ward: str | None, ptype: str | None, scope: str = "ward") -> dict:
    """Our own index as ``[(YYYY-MM, level)]``: the repeat-listing index for (ward, ptype) when ``scope='ward'``,
    else (city, ptype); then the hedonic index (city, all types). Returns ``{series, source, tried}`` — ``series``
    empty when nothing could be built (each failure's reason is in ``tried``)."""
    from vnrealty.market.index import hedonic_index, repeat_index
    tried = []
    attempts = []
    if scope == "ward" and ward:
        attempts.append(("repeat", ward, ptype))
    attempts.append(("repeat", None, ptype))
    for kind, w, p in attempts:
        r = repeat_index(con, as_of, ward_code=w, ptype=p)
        if isinstance(r, Insufficient):
            tried.append({"index": f"repeat:{w or 'city'}:{p}", "reason": r.reason})
            continue
        pts = [(m["month"], m["index"]) for m in r["months"] if m.get("index") is not None]
        if len(pts) >= 2:
            return {"series": pts, "source": f"own-repeat:{w or 'city'}:{p or 'all'}", "tried": tried}
        tried.append({"index": f"repeat:{w or 'city'}:{p}", "reason": "fewer than 2 index months"})
    h = hedonic_index(con, as_of)
    if isinstance(h, Insufficient):
        tried.append({"index": "hedonic:city", "reason": h.reason})
        return {"series": [], "source": None, "tried": tried}
    pts = [(m["month"], m["index"]) for m in h["months"] if m.get("index") is not None]
    return {"series": pts, "source": "own-hedonic:city", "tried": tried}


def drift_vol(series: list[tuple[str, float]], min_months: int = 12) -> dict | Insufficient:
    """Annual drift and volatility from monthly log changes of an index (consecutive months only):
    drift = exp(12·mean) − 1, vol = sd·√12. Insufficient with fewer than ``min_months`` monthly changes."""
    from vnrealty.forecast.series import month_diff
    ch = [math.log(b / a) for (ma, a), (mb, b) in zip(series, series[1:])
          if a and b and a > 0 and b > 0 and month_diff(ma, mb) == 1]
    if len(ch) < min_months:
        return Insufficient("drift_vol", f"{len(ch)} monthly index changes (< {min_months}) to estimate drift and "
                                         f"volatility; pass --drift and --vol")
    mu = sum(ch) / len(ch)
    sd = math.sqrt(sum((x - mu) ** 2 for x in ch) / (len(ch) - 1))
    return {"drift": math.exp(12 * mu) - 1, "vol": sd * math.sqrt(12), "n_changes": len(ch),
            "basis": "own index monthly log changes, annualised"}


def fit_hedonic(con, as_of: str, ptype: str | None, ward: str | None = None):
    """The hedonic model for one property type (and ward); when that sample cannot be fitted, the pooled model
    (all types, ptype dummies) over the same ward filter. The Insufficient lists both reasons."""
    from vnrealty.valuation import hedonic
    base = {"ward_codes": [ward]} if ward else {}
    tried = []
    for f in ([{**base, "ptype": ptype}] if ptype else []) + [base]:
        m = hedonic.fit(con, as_of, filters=f or None)
        if not isinstance(m, Insufficient):
            m.detail["cli_filters"] = f
            return m
        tried.append({"filters": f, "reason": m.reason})
    return Insufficient("hedonic", "; ".join(f"{t['filters'] or 'pooled'}: {t['reason']}" for t in tried),
                        {"tried": tried})


def run_value(con, subject: dict, as_of: str, record: bool = True) -> dict:
    """Comps + hedonic (+ index-moved when the subject has a purchase and an index exists) → triangulated with
    weights earned from calibration → each recorded in the calibration record. The official table is reported as a
    floor beside the result."""
    from vnrealty.valuation import calibrate, comps, hedonic, index_moved, triangulate
    ests: list = []
    # since the 2025 merger a "ward" can span several old wards: with coordinates, try comps within 3 km first
    c = comps.value_by_comps(con, subject, as_of, radius_km=COMPS_RADIUS_KM) if subject.get("lat") is not None else None
    if c is None or isinstance(c, Insufficient):
        c = comps.value_by_comps(con, subject, as_of)
    ests.append(c)
    model = fit_hedonic(con, as_of, subject.get("ptype"))
    h = hedonic.predict(model, subject) if not isinstance(model, Insufficient) else \
        Insufficient("hedonic", model.reason, model.detail)
    ests.append(h)
    im = None
    if subject.get("cost") and subject.get("bought_at"):
        idx = index_series(con, as_of, subject.get("ward_code"), subject.get("ptype"))
        if idx["series"]:
            im = index_moved.value_by_index(subject["cost"], str(subject["bought_at"])[:7], idx["series"], as_of)
            if isinstance(im, Estimate):
                im.detail["index_source"] = idx["source"]
        else:
            im = Insufficient("index_moved", "no index series", {"tried": idx["tried"]})
        ests.append(im)
    good = [e.method for e in ests if isinstance(e, Estimate)]
    weights = triangulate.method_weights(con, as_of, methods=good) if good else {}
    combined = triangulate.combine(ests, weights or None)
    recorded = []
    if record:
        inputs = {k: subject.get(k) for k in ("ptype", "ward_code", "area_m2", "alley_m", "corner", "legal", "ask")}
        for e in ests + [combined]:
            recorded.append(calibrate.record(con, subject["subject"], e, inputs=inputs, as_of=as_of))
    val = combined.value if isinstance(combined, Estimate) else None
    return {"subject": subject, "methods": {e.method: e for e in ests}, "official_floor": official_floor(subject),
            "weights": weights, "combined": combined, "ask": subject.get("ask"),
            "gap_to_ask": gap_to_ask(val, subject.get("ask")), "recorded": recorded,
            "status": "ok" if isinstance(combined, Estimate) else "insufficient"}


# ------------------------------------------------------------------ deals

def deal_from_dict(d: dict) -> Deal | Insufficient:
    """A Deal from JSON fields. Keys starting with '_' (notes) and ``name``/``subject``/``est_value``/``area_m2``
    are ignored; an unknown key is an error; a field set to null is a missing input (Insufficient names them)."""
    names = {f.name for f in dataclasses.fields(Deal)}
    meta = {"name", "subject", "est_value", "area_m2", "preset", "extra", "scenarios", "kill"}
    unknown = [k for k in d if not k.startswith("_") and k not in names and k not in meta]
    if unknown:
        raise CliError(f"unknown Deal fields {unknown}; known: {sorted(names)}")
    missing = [k for k in names if k in d and d[k] is None]
    if missing:
        return Insufficient("deal", "missing inputs: " + ", ".join(sorted(missing)), {"missing": sorted(missing)})
    kw = {}
    for f in dataclasses.fields(Deal):
        if f.name in d:
            v = d[f.name]
            kw[f.name] = int(v) if f.type in ("int", int) else float(v)
    return Deal(**kw)


def load_deal(path: str) -> tuple[dict, Deal | Insufficient]:
    d = load_json(path, "deal")
    if not isinstance(d, dict):
        raise CliError(f"{path}: a deal file must be a JSON object of Deal fields")
    return d, deal_from_dict(d)


_MARKET = ("price", "value_after", "rent", "loan", "teaser_rate", "float_rate", "price_growth", "rent_growth",
           "hurdle", "renovation")

#: Deal presets: the *shape* of a deal type (timing, cost structure). Market inputs are null and must be filled from
#: the listing, `value`, `market rents`, the bank and reference/*.json — a preset never supplies a market number.
PRESETS: dict[str, dict] = {
    "build_rent": {"_about": "land + studios to rent (xây trọ / căn hộ mini)",
                   "build_cost": None, "build_months": 8, "building_life_years": 30, "lease_up_months": 3,
                   "ramp_months": 6, "vacancy": 0.10, "management": 0.05, "running_costs": None},
    "homestay": {"_about": "buy + fit out + run as a homestay (rent field = monthly revenue)",
                 "lease_up_months": 2, "ramp_months": 6, "vacancy": 0.0, "management": 0.15, "cogs": 0.10,
                 "staff": None, "rent_tax": 0.07, "running_costs": None},
    "chdv": {"_about": "serviced apartments (CHDV): building fit-out, monthly tenants",
             "lease_up_months": 2, "ramp_months": 4, "vacancy": 0.10, "management": 0.08, "cogs": 0.05,
             "staff": None, "rent_tax": 0.07, "running_costs": None},
    "apartment": {"_about": "buy an apartment and let it", "lease_up_months": 2, "vacancy": 0.08,
                  "management": 0.05, "running_costs": None},
    "shophouse": {"_about": "buy a shophouse, ground floor let to a business", "lease_up_months": 3,
                  "vacancy": 0.10, "management": 0.03, "running_costs": None},
    "land": {"_about": "land bank: no income, value from price growth", "renovation": 0.0, "lease_up_months": 0,
             "rent": 0.0, "rent_growth": 0.0, "vacancy": 0.0, "management": 0.0, "rent_tax": 0.0,
             "running_costs": None, "loan": 0.0},
}

_SOURCES = {
    "price": "the listing's asking price (`listings --json`) or the agreed price",
    "value_after": "`value <subject> --json` combined value (after renovation if any)",
    "rent": "`market rents --ward … --json` × area (or revenue for a business), never the seller's claim",
    "loan": "VND; 0 for no loan", "teaser_rate": "bank offer (reference/bank_lending.json)",
    "float_rate": "bank floating rate", "price_growth": "`project` / `forecast` (annual fraction)",
    "rent_growth": "annual fraction (judgement, state it)", "hurdle": "your required return (profile)",
    "renovation": "VND quote", "build_cost": "GFA × reference/pricing_params.json build_cost_m2",
    "running_costs": "VND per month: upkeep, insurance, utilities", "staff": "VND per month",
}


def preset_template(name: str, subject: dict | None = None) -> dict:
    """A deal JSON template: every Deal field, the preset's shape values, market inputs null with their source.
    With a subject the asking price fills ``price``."""
    if name not in PRESETS:
        raise CliError(f"unknown preset {name!r}; one of {sorted(PRESETS)}")
    p = PRESETS[name]
    t: dict = {"_preset": name, "_about": p["_about"],
               "_basis": "shape values are judgement templates; null fields must be filled from the cited sources"}
    for f in dataclasses.fields(Deal):
        if f.name in p:
            t[f.name] = p[f.name]
        elif f.name in _MARKET:
            t[f.name] = None
        else:
            t[f.name] = f.default
    t["_fill"] = {k: _SOURCES.get(k, "") for k, v in t.items() if not k.startswith("_") and v is None}
    if subject:
        t["subject"] = subject["subject"]
        if subject.get("area_m2"):
            t["area_m2"] = subject["area_m2"]
        if subject.get("ask") is not None:
            t["price"] = subject["ask"]
            t["_fill"].pop("price", None)
    return t


# ------------------------------------------------------------------ listings / screens

def days_before(as_of: str, days: int) -> str:
    return (_dt.date.fromisoformat(as_of[:10]) - _dt.timedelta(days=days)).isoformat()


def listing_rows(con, as_of: str, deal: str = "sale", ward: str | None = None, ptype: str | None = None,
                 min_price: float | None = None, max_price: float | None = None, watched: bool = False,
                 since: str | None = None, limit: int | None = None) -> list[dict]:
    """Listings with their latest priced observation at or before ``as_of`` (asking/sale, or rent for rentals)."""
    end = as_of if len(as_of) > 10 else as_of + "T99"
    kinds = ("rent",) if deal == "rent" else ("asking", "sale")
    q = (f"SELECT l.id, l.ptype, l.deal, l.ward_code, l.title, l.street, l.address, l.lat, l.lng, l.area_m2, "
         f"l.frontage_m, l.alley_m, l.corner, l.legal, l.floors, l.bedrooms, l.status, l.watch, l.first_seen, "
         f"o.price, o.price_m2, o.seen_at, o.kind, o.site, o.url "
         f"FROM listing l JOIN listing_obs o ON o.listing_id = l.id "
         f"WHERE l.deal = ? AND o.price IS NOT NULL AND o.seen_at <= ? AND o.kind IN ({','.join('?' * len(kinds))}) "
         f"AND o.seen_at = (SELECT MAX(o2.seen_at) FROM listing_obs o2 WHERE o2.listing_id = l.id "
         f"AND o2.price IS NOT NULL AND o2.seen_at <= ? AND o2.kind IN ({','.join('?' * len(kinds))}))")
    args: list = [deal, end, *kinds, end, *kinds]
    if ward:
        q += " AND l.ward_code = ?"
        args.append(ward)
    if ptype:
        ps = [p.strip() for p in ptype.split(",") if p.strip()]
        q += f" AND l.ptype IN ({','.join('?' * len(ps))})"
        args += ps
    if min_price is not None:
        q += " AND o.price >= ?"
        args.append(min_price)
    if max_price is not None:
        q += " AND o.price <= ?"
        args.append(max_price)
    if watched:
        q += " AND l.watch = 1"
    if since:
        q += " AND o.seen_at >= ?"
        args.append(since)
    q += " GROUP BY l.id ORDER BY o.seen_at DESC, l.id DESC"
    if limit:
        q += f" LIMIT {int(limit)}"
    out = []
    for r in con.execute(q, args).fetchall():
        d = dict(r)
        d["corner"] = None if d["corner"] is None else bool(d["corner"])
        out.append(d)
    return out


def listing_yield(row: dict, ward_rent_m2: float | None) -> float | None:
    """Asking gross yield of one listing = 12 × ward median asking rent per m² ÷ the listing's asking price per m².
    None when either side is missing."""
    ppm = row.get("price_m2") or ((row["price"] / row["area_m2"]) if row.get("price") and row.get("area_m2") else None)
    if not ppm or not ward_rent_m2:
        return None
    return 12 * ward_rent_m2 / ppm


# ------------------------------------------------------------------ profile / household / params

def load_profile(path: str | None, data_dir: Path):
    """InvestorProfile from ``path`` (fields, or ``{"answers": {...}}``), else data/portfolio/profile.json, else the
    'balanced' preset (judgement). Returns (profile, source)."""
    from vnrealty.strategy.profile import InvestorProfile, profile_from_answers
    src = path
    if src is None:
        p = data_dir / "portfolio" / "profile.json"
        if p.exists():
            src = str(p)
    if src is None:
        return InvestorProfile(), "preset default (balanced; judgement)"
    d = load_json(src, "profile")
    if isinstance(d, dict) and "answers" in d:
        return profile_from_answers(d["answers"]), src
    names = {f.name for f in dataclasses.fields(InvestorProfile)}
    kw = {k: (tuple(v) if k == "strategies_allowed" and v is not None else v) for k, v in d.items() if k in names}
    return InvestorProfile(**kw), src


def load_household(path: str | None, data_dir: Path):
    """Household from ``path`` or data/portfolio/household.json. Raises CliError when neither exists."""
    from vnrealty.plan.finplan import Household
    src = path or (str(data_dir / "portfolio" / "household.json")
                   if (data_dir / "portfolio" / "household.json").exists() else None)
    if src is None:
        raise CliError("no household file: pass --household FILE or save data/portfolio/household.json")
    d = load_json(src, "household")
    names = {f.name for f in dataclasses.fields(Household)}
    unknown = [k for k in d if k not in names and not k.startswith("_")]
    if unknown:
        raise CliError(f"unknown Household fields {unknown}; known: {sorted(names)}")
    return Household(**{k: v for k, v in d.items() if k in names}), src


def sell_costs() -> float:
    """Selling costs as a fraction (2% seller PIT + ~1% broker) from reference/strategy_params.json common."""
    from vnrealty.strategy.catalog import params
    return float(params()["common"]["sell_costs"]["value"])
