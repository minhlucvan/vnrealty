"""Sales-comparison valuation: pick comparables, adjust them to the subject, value the subject.

Ported from the method of a hand-built land valuation (comparable asking prices in an area band, an explicit
asking→sale haircut, a corner premium) and generalised:

* **Point in time.** For each listing only its *latest* priced ``listing_obs`` with ``seen_at <= as_of`` (and inside
  the look-back window) is used. ``sale_evidence`` with ``sold_at <= as_of`` is preferred: when a listing has a sale,
  its asking observations are dropped.
* **Asking is not selling.** Asking comps are multiplied by the cited ``asking_to_sale`` haircut, explicitly, and the
  haircut used (central / lo / hi) is written into ``Estimate.detail``.
* **Missing numbers announce themselves.** An attribute unknown on either side is *not* adjusted; the adjustment is
  recorded as ``"unknown"``. Fewer than ``min_n`` comps returns ``Insufficient``.

Units: money VND, area m², price per m² VND/m², distances km, widths m.

The subject is a dict: ``ptype, ward_code, lat, lng, area_m2, frontage_m, alley_m (0 = street frontage), access
('kiet' | 'street' when the class is known but the width is not), corner,
legal``. Parameters come from ``reference/market_params.json`` (each with a ``basis`` and sources).
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from vnrealty.stats import median, quantile
from vnrealty.store.db import REPO
from vnrealty.types import Comp, Estimate, Insufficient

__all__ = ["load_params", "haversine_km", "select_comps", "adjust", "alley_factor", "value_by_comps",
           "end_of", "months_back"]

PARAMS_PATH = REPO / "reference" / "market_params.json"
ATTRS = ("corner", "alley_m", "frontage_m", "legal", "area_m2", "ward_code", "lat", "lng")


def load_params(path: str | Path | None = None) -> dict:
    """Load the ``params`` block of ``reference/market_params.json`` (or ``path``)."""
    with open(path or PARAMS_PATH, encoding="utf-8") as fh:
        return json.load(fh)["params"]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two WGS84 points (degrees)."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def end_of(as_of: str) -> str:
    """Upper bound for ISO string comparison: a bare date ``YYYY-MM-DD`` includes the whole day."""
    return as_of + "T23:59:59.999" if len(as_of) == 10 else as_of


def months_back(as_of: str, months: int) -> str:
    """ISO date ``months`` calendar months before ``as_of`` (day clamped to the month's end)."""
    d = date.fromisoformat(as_of[:10])
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day).isoformat()
        except ValueError:
            continue
    return date(y, m, 28).isoformat()


def _rows(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def _in_place(subject: dict, row: dict, radius_km: float | None) -> tuple[bool, float | None]:
    """Whether a candidate is 'nearby', and its distance in km when both sides have coordinates."""
    dist = None
    if None not in (subject.get("lat"), subject.get("lng"), row.get("lat"), row.get("lng")):
        dist = haversine_km(subject["lat"], subject["lng"], row["lat"], row["lng"])
    if radius_km is not None:
        return (dist is not None and dist <= radius_km), dist
    sw = subject.get("ward_code")
    return (sw is not None and row.get("ward_code") == sw), dist


def select_comps(con: sqlite3.Connection, subject: dict, as_of: str, radius_km: float | None = None,
                 area_band: tuple[float, float] = (0.75, 1.3), months: int = 12) -> list[Comp]:
    """Comparables for ``subject`` visible at ``as_of`` (unadjusted: ``adj_price_m2 == price_m2``). When ``subject``
    carries ``listing_id``, that listing (and its own sale evidence) is excluded.

    Same ``ptype``; same ward (or within ``radius_km`` when given — then both sides need coordinates); area within
    ``area_band`` × subject area (m²); observed within ``months`` before ``as_of``. Sales (``kind='sale'``) come from
    ``sale_evidence`` and supersede asking observations of the same listing. Each comp's attributes are kept in
    ``comp.adjustments['attrs']`` for :func:`adjust`.
    """
    area = subject.get("area_m2")
    if not area or not subject.get("ptype"):
        return []
    lo_a, hi_a = area * area_band[0], area * area_band[1]
    end, start = end_of(as_of), months_back(as_of, months)
    out: list[Comp] = []
    sold_listings: set[int] = set()

    sales = _rows(con, """
        SELECT s.id AS sid, s.listing_id, s.sold_at, s.price, s.source, s.url,
               COALESCE(s.ward_code, l.ward_code) AS ward_code, COALESCE(s.ptype, l.ptype) AS ptype,
               COALESCE(s.area_m2, l.area_m2) AS area_m2, l.lat, l.lng, l.corner, l.alley_m, l.frontage_m, l.legal
        FROM sale_evidence s LEFT JOIN listing l ON l.id = s.listing_id
        WHERE s.sold_at <= ? AND s.sold_at >= ?""", (end, start))
    for r in sales:
        if r["ptype"] != subject["ptype"] or not r["area_m2"] or not (lo_a <= r["area_m2"] <= hi_a) or r["price"] <= 0:
            continue
        ok, dist = _in_place(subject, r, radius_km)
        if not ok:
            continue
        if r["listing_id"] is not None:
            sold_listings.add(r["listing_id"])
        ppm = r["price"] / r["area_m2"]
        out.append(Comp(listing_id=r["listing_id"], price=r["price"], area_m2=r["area_m2"], price_m2=ppm,
                        adj_price_m2=ppm, kind="sale", seen_at=r["sold_at"], distance_km=dist,
                        adjustments={"attrs": {k: r.get(k) for k in ATTRS}},
                        source=f"sale_evidence:{r['sid']} {r['source']}" + (f" {r['url']}" if r["url"] else "")))

    asks = _rows(con, """
        SELECT l.id AS listing_id, l.ptype, l.ward_code, l.lat, l.lng, l.area_m2, l.corner, l.alley_m, l.frontage_m,
               l.legal, o.seen_at, o.price, o.site, o.url, o.kind
        FROM listing l JOIN listing_obs o ON o.listing_id = l.id
        WHERE l.deal = 'sale' AND l.ptype = ? AND o.kind = 'asking' AND o.price IS NOT NULL
          AND o.seen_at = (SELECT MAX(o2.seen_at) FROM listing_obs o2
                           WHERE o2.listing_id = l.id AND o2.kind = 'asking' AND o2.price IS NOT NULL
                             AND o2.seen_at <= ?)
          AND o.seen_at >= ?""", (subject["ptype"], end, start))
    seen: set[int] = set()
    for r in asks:
        if r["listing_id"] in sold_listings or r["listing_id"] in seen:
            continue
        if not r["area_m2"] or not (lo_a <= r["area_m2"] <= hi_a) or r["price"] <= 0:
            continue
        ok, dist = _in_place(subject, r, radius_km)
        if not ok:
            continue
        seen.add(r["listing_id"])
        ppm = r["price"] / r["area_m2"]
        out.append(Comp(listing_id=r["listing_id"], price=r["price"], area_m2=r["area_m2"], price_m2=ppm,
                        adj_price_m2=ppm, kind="asking", seen_at=r["seen_at"], distance_km=dist,
                        adjustments={"attrs": {k: r.get(k) for k in ATTRS}},
                        source=f"{r['site']} {r['url'] or ''}".strip()))
    own = subject.get("listing_id")   # a listing is never its own comparable
    out = [c for c in out if own is None or c.listing_id != own]
    # access class known even when the width is not: a lot in a kiệt is never priced off street-front comps (or vice versa)
    acc = subject.get("access") if subject.get("alley_m") is None else None
    if acc in ("kiet", "street"):
        def _class_ok(c: Comp) -> bool:
            ca = (c.adjustments.get("attrs") or {}).get("alley_m")
            return ca is None or (ca > 0 if acc == "kiet" else ca == 0)
        out = [c for c in out if _class_ok(c)]
    return out


def alley_factor(alley_m: float, curve: list[list[float]]) -> float:
    """Price/m² relative to street frontage for a kiệt of width ``alley_m`` metres (0 = street), linear on ``curve``."""
    pts = sorted(curve)
    if alley_m <= 0:
        return pts[0][1]
    if alley_m >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= alley_m <= x1:
            return y0 + (y1 - y0) * (alley_m - x0) / (x1 - x0) if x1 > x0 else y1
    return pts[-1][1]


def _frontage_mult(f: float, p: dict) -> float:
    return 1 + max(-p["cap"], min(p["cap"], p["per_m"] * (f - p["ref_m"])))


def adjust(comp: Comp, subject: dict, params: dict | None = None) -> Comp:
    """Adjust ``comp`` toward ``subject``; returns a new Comp with ``adj_price_m2`` (VND/m²) and per-factor detail.

    Factors (each subject-over-comp, multiplicative on price/m²): corner premium, alley-width curve (street vs kiệt),
    frontage, legal (giấy tay discount), size elasticity. A factor whose input is unknown on either side is 1.0 and
    is recorded as ``"unknown"`` — never guessed.
    """
    p = params or load_params()
    a = (comp.adjustments or {}).get("attrs", {})
    f: dict[str, Any] = {}

    sc, cc = subject.get("corner"), a.get("corner")
    if sc is None or cc is None:
        f["corner"] = "unknown"
    else:
        prem = p["corner_premium"]["value"]
        f["corner"] = (1 + prem * bool(sc)) / (1 + prem * bool(cc))

    sa, ca = subject.get("alley_m"), a.get("alley_m")
    if sa is None or ca is None:
        f["alley"] = "unknown"
    else:
        curve = p["alley_curve"]["points"]
        f["alley"] = alley_factor(sa, curve) / alley_factor(ca, curve)

    sf, cf = subject.get("frontage_m"), a.get("frontage_m")
    if sf is None or cf is None:
        f["frontage"] = "unknown"
    else:
        f["frontage"] = _frontage_mult(sf, p["frontage"]) / _frontage_mult(cf, p["frontage"])

    lf = p["legal"]["factors"]
    sl, cl = subject.get("legal"), a.get("legal")
    if sl not in lf or cl not in lf:
        f["legal"] = "unknown"
    else:
        f["legal"] = lf[sl] / lf[cl]

    s_area = subject.get("area_m2")
    if not s_area or not comp.area_m2:
        f["size"] = "unknown"
    else:
        f["size"] = (s_area / comp.area_m2) ** p["size"]["elasticity"]

    mult = 1.0
    for v in f.values():
        if isinstance(v, float):
            mult *= v
    adj = dict(comp.adjustments or {})
    adj["factors"] = f
    adj["multiplier"] = mult
    return Comp(listing_id=comp.listing_id, price=comp.price, area_m2=comp.area_m2, price_m2=comp.price_m2,
                adj_price_m2=comp.price_m2 * mult, kind=comp.kind, seen_at=comp.seen_at,
                distance_km=comp.distance_km, adjustments=adj, source=comp.source)


def value_by_comps(con: sqlite3.Connection, subject: dict, as_of: str, params: dict | None = None, min_n: int = 5,
                   radius_km: float | None = None, area_band: tuple[float, float] = (0.75, 1.3),
                   months: int = 12) -> Estimate | Insufficient:
    """Value ``subject`` (VND) by adjusted comparables at ``as_of``.

    value = median sale-equivalent adjusted price/m² × subject area; lo = 25th percentile (asking comps at the
    *harsher* haircut ``lo``) × area; hi = 75th percentile (asking comps at the *milder* haircut ``hi``) × area.
    Sales are never haircut. ``Insufficient`` when the subject lacks area/ptype or fewer than ``min_n`` comps exist.
    """
    m = "comps"
    if not subject.get("area_m2") or not subject.get("ptype"):
        return Insufficient(m, "subject needs ptype and area_m2")
    p = params or load_params()
    comps = [adjust(c, subject, p) for c in select_comps(con, subject, as_of, radius_km, area_band, months)]
    if len(comps) < min_n:
        return Insufficient(m, f"{len(comps)} comparables (< {min_n}) for {subject.get('ptype')} in "
                               f"{'radius %.2f km' % radius_km if radius_km is not None else subject.get('ward_code')} "
                               f"within {months} months of {as_of}", {"n": len(comps)})
    hc = p["asking_to_sale"]
    pools = {k: [c.adj_price_m2 * (hc[k] if c.kind == "asking" else 1.0) for c in comps] for k in ("lo", "value", "hi")}
    A = subject["area_m2"]
    mid = median(pools["value"]) * A
    lo = quantile(pools["lo"], 0.25) * A
    hi = quantile(pools["hi"], 0.75) * A
    n_sale = sum(c.kind == "sale" for c in comps)
    detail = {
        "haircut": {"applied_to": "asking comps only", "value": hc["value"], "lo": hc["lo"], "hi": hc["hi"],
                    "basis": hc.get("basis")},
        "n_sale": n_sale, "n_asking": len(comps) - n_sale,
        "median_adj_price_m2_sale_equiv": median(pools["value"]),
        "comps": [{"listing_id": c.listing_id, "kind": c.kind, "seen_at": c.seen_at, "area_m2": c.area_m2,
                   "price": c.price, "price_m2": c.price_m2, "adj_price_m2": c.adj_price_m2,
                   "distance_km": c.distance_km, "factors": c.adjustments.get("factors"), "source": c.source}
                  for c in comps],
        "params_ref": "reference/market_params.json",
    }
    return Estimate(m, mid, min(lo, mid), max(hi, mid), n=len(comps), as_of=as_of, detail=detail)
