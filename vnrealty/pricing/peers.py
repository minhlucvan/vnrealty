"""Peer statistics: where a listing sits among comparable listings, in the unit that prices its type.

**Units** (:data:`UNITS`; :func:`unit_for` picks the default per type)::

    land, house, villa, other   price_m2              VND per m² of land          (price / area_m2)
    apartment                   price_m2_floor        VND per m² of floor area    (price / floor_area_m2, else area_m2)
    shophouse                   price_per_frontage_m  VND per metre of frontage   (price / frontage_m)
    chdv, room                  price_per_room        VND per room (key)          (price / rooms)
    any rental (deal='rent')    rent_m2               VND per m² per month        (rent / area_m2)

plus ``price_per_buildable_m2`` (price / zoning GFA, :mod:`vnrealty.pricing.zoning`), ``rent_month`` (VND/month per
listing), ``rent_per_frontage_m`` (VND/month per metre) and ``price`` (VND). Rooms are ``listing.bedrooms`` or the
observation's ``extra.rooms`` / ``extra.units``.

**Point in time.** Each listing contributes its latest priced observation with ``seen_at <= as_of`` (and inside the
``months`` look-back) of kind ``asking`` (sale listings) or ``rent`` (rentals). Asking is compared with asking —
these are relative statistics, not valuations, so no haircut is applied. The subject itself is excluded.

**Scope ladder** (when ``'ward_code'`` is in ``by``; the first scope with ``n >= min_n`` wins and is reported):

1. ``ward`` — same ward (and other ``by`` keys), area within ``area_band`` × subject area when a band is given;
2. ``ward_wide_band`` — same ward, band widened to (lo × 2/3, hi × 1.5) — only when a band was given;
3. ``old_district`` — wards sharing the subject ward's pre-2025 district (``ward.old_district``), wide band;
4. ``city`` — every ward, wide band.

Below ``min_n`` at city level → :class:`~vnrealty.types.Insufficient` (with the ladder tried). An optional
``project`` scope (apartments of the same matched project, :func:`project_key`) is tried before the ward.

**Statistics.** n, median, p25/p75 and IQR, MAD; the subject's percentile = 100 × (#peers below + ½ #ties) / n and
robust z = (x − median) / (1.4826 · MAD) (None when MAD = 0).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from vnrealty.listings.parse import fold
from vnrealty.stats import iqr, mad, median
from vnrealty.types import Insufficient
from vnrealty.valuation.comps import end_of, months_back

from . import zoning

__all__ = ["UNITS", "unit_for", "unit_value", "rooms_of", "project_key", "snapshot", "PeerCache", "peer_stats"]

UNITS = {
    "price_m2": "VND/m² land",
    "price_m2_floor": "VND/m² floor area",
    "price_per_frontage_m": "VND/m frontage",
    "price_per_room": "VND/room",
    "price_per_buildable_m2": "VND/m² buildable GFA",
    "price": "VND",
    "rent_m2": "VND/m²/month",
    "rent_month": "VND/month",
    "rent_per_frontage_m": "VND/month per m frontage",
}
_BY_TYPE = {"land": "price_m2", "house": "price_m2", "villa": "price_m2", "other": "price_m2",
            "apartment": "price_m2_floor", "shophouse": "price_per_frontage_m", "chdv": "price_per_room",
            "room": "price_per_room"}
K_MAD = 1.4826
_LCOLS = ("id", "ptype", "deal", "title", "address", "street", "ward_code", "lat", "lng", "area_m2", "floor_area_m2",
          "frontage_m", "depth_m", "alley_m", "floors", "bedrooms", "corner", "direction", "legal", "first_seen",
          "last_seen", "status")


def unit_for(ptype: str | None, deal: str | None = "sale") -> str:
    """Default peer unit for a property type (``rent_m2`` for any rental)."""
    if deal == "rent":
        return "rent_m2"
    return _BY_TYPE.get(ptype or "other", "price_m2")


def rooms_of(row: dict) -> float | None:
    """Rooms (keys) of a listing: ``extra.rooms`` / ``extra.units`` if stated, else ``bedrooms``; None if unknown."""
    ex = row.get("extra")
    if isinstance(ex, str):
        try:
            ex = json.loads(ex)
        except ValueError:
            ex = None
    if isinstance(ex, dict):
        for k in ("rooms", "units"):
            v = ex.get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
    b = row.get("bedrooms")
    return float(b) if b and b > 0 else None


def unit_value(row: dict, unit: str, params: dict | None = None) -> float | None:
    """The row's value in ``unit`` (see :data:`UNITS`) from its ``price`` (VND, or VND/month for rent); None when an
    input is missing or non-positive."""
    p = row.get("price")
    if not p or p <= 0:
        return None
    if unit in ("price", "rent_month"):
        return float(p)
    if unit in ("price_m2", "rent_m2"):
        a = row.get("area_m2")
        return p / a if a and a > 0 else None
    if unit == "price_m2_floor":
        fa = zoning.floor_area(row, params)
        return p / fa[0] if fa else None
    if unit in ("price_per_frontage_m", "rent_per_frontage_m"):
        f = row.get("frontage_m")
        return p / f if f and f > 0 else None
    if unit == "price_per_room":
        r = rooms_of(row)
        return p / r if r else None
    if unit == "price_per_buildable_m2":
        g = zoning.gfa(row.get("area_m2"), row.get("alley_m"), row.get("road_width_m"), params)
        return p / g["gfa_m2"] if isinstance(g, dict) and g["gfa_m2"] > 0 else None
    raise ValueError(f"unknown unit {unit!r}")


_PROJ_KW = re.compile(r"\b(?:chung cu|can ho|du an|toa nha|khu can ho|toa)\s+")
_PROJ_LEAD = {"chung", "cu", "can", "ho", "du", "toa", "nha", "khu", "cao", "cap"}
_PROJ_STOP = {"ban", "gia", "re", "view", "huong", "bien", "song", "tang", "phong", "ngu", "pn", "dep", "full", "noi",
              "that", "chinh", "chu", "mini", "dich", "vu", "tai", "o", "quan", "phuong", "duong", "so", "hong",
              "studio", "trung", "tam", "gan", "sat", "ngay", "cho", "thue", "can", "goc", "lau", "dt", "dien", "tich",
              "tp", "thanh", "pho", "da", "nang", "1pn", "2pn", "3pn", "4pn", "moi", "cuc", "hot", "chi", "ty", "tr",
              "trieu", "m2", "va", "voi", "khong", "nhanh", "can", "1", "2", "3", "4"}


def project_key(*texts: str | None) -> str | None:
    """A diacritics-folded project/building name from listing text, e.g. 'Bán căn hộ Monarchy B view sông' →
    'monarchy b'. The first keyword (chung cư / căn hộ / dự án / tòa) followed by 1–4 name tokens, stopping at generic
    words. None when nothing name-like follows a keyword — a heuristic for grouping peers, never an identity."""
    for t in texts:
        f = fold(t)
        for m in _PROJ_KW.finditer(f):
            toks = re.split(r"[\s,.;:()\-/|]+", f[m.end():])
            while toks and toks[0] in _PROJ_LEAD:
                toks.pop(0)
            name = []
            for tok in toks:
                if not tok or tok in _PROJ_STOP or re.fullmatch(r"\d+(m2|m|pn|ty|tr)?", tok):
                    break
                name.append(tok)
                if len(name) == 4:
                    break
            key = " ".join(name)
            if len(key.replace(" ", "")) >= 3:
                return key
    return None


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days


def snapshot(con: sqlite3.Connection, listing_id: int, as_of: str) -> dict | Insufficient:
    """One listing as known at ``as_of``: its listing columns, the latest priced observation (``price`` VND or
    VND/month, ``seen_at``, ``extra``) and its observation history up to ``as_of``.

    Adds ``first_obs`` (earliest ``seen_at`` or ``posted_at`` ≤ as_of), ``days_on_market`` (as_of − first_obs, days),
    ``cuts`` (number of price decreases between consecutive priced observations), ``cut_total`` (latest ÷ highest
    earlier price − 1, ≤ 0) and ``negotiable`` (any observation without a number, i.e. 'thỏa thuận').
    Insufficient when the listing does not exist or has no observation at ``as_of``.
    """
    r = con.execute(f"SELECT {', '.join(_LCOLS)} FROM listing WHERE id = ?", (listing_id,)).fetchone()
    if r is None:
        return Insufficient("snapshot", f"listing {listing_id} not found")
    row = dict(r)
    kind = "rent" if row["deal"] == "rent" else "asking"
    obs = [dict(o) for o in con.execute(
        "SELECT seen_at, price, posted_at, extra, kind FROM listing_obs WHERE listing_id = ? AND seen_at <= ? "
        "AND kind = ? ORDER BY seen_at", (listing_id, end_of(as_of), kind))]
    if not obs:
        return Insufficient("snapshot", f"listing {listing_id} has no {kind} observation at {as_of}")
    priced = [o for o in obs if o["price"] is not None and o["price"] > 0]
    starts = [o["seen_at"] for o in obs] + [o["posted_at"] for o in obs if o["posted_at"] and o["posted_at"] <= as_of]
    first = min(s[:10] for s in starts)
    cuts, cut_total = 0, 0.0
    for a, b in zip(priced, priced[1:]):
        if b["price"] < a["price"]:
            cuts += 1
    if len(priced) >= 2:
        hi = max(o["price"] for o in priced[:-1])
        cut_total = min(0.0, priced[-1]["price"] / hi - 1)
    last = priced[-1] if priced else None
    row.update({"price": last["price"] if last else None, "seen_at": last["seen_at"] if last else obs[-1]["seen_at"],
                "extra": last["extra"] if last else obs[-1]["extra"], "first_obs": first,
                "days_on_market": _days(first, as_of), "cuts": cuts, "cut_total": cut_total,
                "negotiable": any(o["price"] is None for o in obs), "n_obs": len(obs)})
    return row


class PeerCache:
    """Peer pools loaded once per (``as_of``, ``months``, deal) and per-scope sorted value lists, so a screen over
    thousands of listings does one query per deal kind and one sort per scope."""

    def __init__(self, con: sqlite3.Connection, as_of: str, months: int = 12, params: dict | None = None):
        self.con, self.as_of, self.months = con, as_of, months
        self.params = params or zoning.load_params()
        self._pools: dict[str, list[dict]] = {}
        self._scopes: dict[tuple, list[tuple[float, int]]] = {}
        self._old: dict[str, str | None] | None = None

    def pool(self, deal: str = "sale") -> list[dict]:
        """Every listing of ``deal`` with its latest priced observation in the window (PIT)."""
        if deal not in self._pools:
            kind = "rent" if deal == "rent" else "asking"
            end, start = end_of(self.as_of), months_back(self.as_of, self.months)
            cols = ", ".join(f"l.{c}" for c in _LCOLS)
            rows = [dict(r) for r in self.con.execute(f"""
                SELECT {cols}, o.price, o.seen_at, o.extra FROM listing l JOIN listing_obs o ON o.listing_id = l.id
                WHERE l.deal = ? AND o.kind = ? AND o.price IS NOT NULL AND o.price > 0
                  AND o.seen_at = (SELECT MAX(o2.seen_at) FROM listing_obs o2 WHERE o2.listing_id = l.id
                                   AND o2.kind = ? AND o2.price IS NOT NULL AND o2.seen_at <= ?)
                  AND o.seen_at >= ?""", (deal, kind, kind, end, start))]
            seen, out = set(), []
            for r in rows:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    out.append(r)
            self._pools[deal] = out
        return self._pools[deal]

    def old_district(self, ward_code: str | None) -> str | None:
        if self._old is None:
            self._old = {r[0]: r[1] for r in self.con.execute("SELECT code, old_district FROM ward")}
        return self._old.get(ward_code) if ward_code else None

    def values(self, deal: str, unit: str, filters: tuple, scope: str, place, band: tuple | None,
               project: str | None) -> list[tuple[float, int]]:
        """Sorted (value, listing_id) for one scope; cached."""
        key = (deal, unit, filters, scope, place, band, project)
        if key not in self._scopes:
            fd = dict(filters)
            out = []
            for r in self.pool(deal):
                if any(r.get(k) != v for k, v in fd.items()):
                    continue
                if scope in ("ward", "ward_wide_band") and r.get("ward_code") != place:
                    continue
                if scope == "old_district" and self.old_district(r.get("ward_code")) != place:
                    continue
                if scope == "project" and project_key(r.get("title"), r.get("address")) != project:
                    continue
                if band is not None:
                    a = _band_area(r, unit)
                    if a is None or not (band[0] <= a <= band[1]):
                        continue
                v = unit_value(r, unit, self.params)
                if v is not None:
                    out.append((v, r["id"]))
            out.sort()
            self._scopes[key] = out
        return self._scopes[key]


def _band_area(r: dict, unit: str) -> float | None:
    if unit == "price_m2_floor":
        return r.get("floor_area_m2") or (r.get("area_m2") if r.get("ptype") == "apartment" else None)
    return r.get("area_m2")


def _subject(con: sqlite3.Connection, s, as_of: str) -> dict | Insufficient:
    if isinstance(s, int):
        return snapshot(con, s, as_of)
    return dict(s)


def peer_stats(con: sqlite3.Connection, listing_or_subject, as_of: str, by: tuple = ("ward_code", "ptype"),
               months: int = 12, min_n: int = 8, area_band: tuple[float, float] | None = None,
               unit: str | None = None, deal: str | None = None, ptype: str | None = None,
               project: str | None = None, project_min_n: int | None = None,
               cache: PeerCache | None = None) -> dict | Insufficient:
    """Peer statistics for a listing id or a subject dict at ``as_of`` (see the module docstring).

    ``unit`` defaults to :func:`unit_for` of the subject's type and deal; ``ptype`` overrides the subject's type
    for the peer filter (e.g. land peers for a house's land value); ``deal`` overrides sale/rent; ``project`` adds
    the project scope first (needing ``project_min_n`` peers, default ``min_n``). Returns ``{unit, unit_label, scope, place, n, median, p25, p75, iqr, mad, subject_value,
    percentile, z, ladder, as_of, months}`` (values in ``unit``); ``subject_value``/``percentile``/``z`` are None when
    the subject has no price or no value in that unit.
    """
    m = "peers"
    s = _subject(con, listing_or_subject, as_of)
    if isinstance(s, Insufficient):
        return Insufficient(m, s.reason)
    if ptype:
        s["ptype"] = ptype
    deal = deal or s.get("deal") or "sale"
    unit = unit or unit_for(s.get("ptype"), deal)
    if unit not in UNITS:
        raise ValueError(f"unknown unit {unit!r}")
    c = cache if cache is not None and cache.as_of == as_of and cache.months == months else PeerCache(con, as_of, months)
    keys = tuple(k for k in by if k != "ward_code")
    if any(s.get(k) is None for k in keys):
        return Insufficient(m, "subject lacks " + ", ".join(k for k in keys if s.get(k) is None))
    filters = tuple((k, s.get(k)) for k in keys)
    x = unit_value(s, unit, c.params) if s.get("price") else None
    sa = _band_area(s, unit)
    band = wide = None
    if area_band is not None and sa:
        band = (sa * area_band[0], sa * area_band[1])
        wide = (sa * area_band[0] * 2 / 3, sa * area_band[1] * 1.5)
    steps: list[tuple[str, object, tuple | None]] = []
    if project:
        steps.append(("project", project, None))
    if "ward_code" in by:
        w = s.get("ward_code")
        if w:
            steps.append(("ward", w, band))
            if band is not None:
                steps.append(("ward_wide_band", w, wide))
            od = c.old_district(w)
            if od:
                steps.append(("old_district", od, wide))
        steps.append(("city", None, wide))
    else:
        steps.append(("city", None, band))
    ladder = []
    sid = s.get("id")
    for scope, place, b in steps:
        vals = [v for v, i in c.values(deal, unit, filters, scope, place, b, project if scope == "project" else None)
                if i != sid]
        ladder.append({"scope": scope, "place": place, "n": len(vals)})
        need = project_min_n if scope == "project" and project_min_n else min_n
        if len(vals) >= need:
            return _stats(vals, x, unit, scope, place, ladder, as_of, months)
    return Insufficient(m, f"{ladder[-1]['n']} peers (< {min_n}) even at {ladder[-1]['scope']} level for "
                           f"{dict(filters)} in {unit}", {"ladder": ladder})


def _stats(vals: list[float], x: float | None, unit: str, scope: str, place, ladder: list, as_of: str,
           months: int) -> dict:
    med, md = median(vals), mad(vals)
    q = iqr(vals)
    pct = z = None
    if x is not None:
        below = sum(v < x for v in vals)
        ties = sum(v == x for v in vals)
        pct = 100.0 * (below + 0.5 * ties) / len(vals)
        z = (x - med) / (K_MAD * md) if md else None
    return {"unit": unit, "unit_label": UNITS[unit], "scope": scope, "place": place, "n": len(vals), "median": med,
            "p25": q[0], "p75": q[1], "iqr": q[1] - q[0], "mad": md, "subject_value": x, "percentile": pct, "z": z,
            "ladder": ladder, "as_of": as_of, "months": months}
