"""Price-per-m² tables and price indices from listing observations. ASKING prices unless ``kind`` says otherwise —
an asking index is not a transaction index, and every output says which it is.

Point in time: only observations with ``seen_at <= as_of``. Each listing contributes at most one observation per
month (its latest that month, any site), so a listing re-captured daily or posted on three sites counts once.
"""
from __future__ import annotations

import math
import sqlite3

from vnrealty.stats import median, ols, quantile
from vnrealty.types import Insufficient

__all__ = ["monthly_obs", "ppm2_table", "repeat_index", "hedonic_index"]


def _end(as_of: str) -> str:
    return as_of + "T99" if len(as_of) == 10 else as_of


def monthly_obs(con: sqlite3.Connection, as_of: str, kind: str = "asking", ward_code: str | None = None,
                ptype: str | None = None, since: str | None = None) -> list[dict]:
    """One row per (listing, month): listing_id, month 'YYYY-MM', price, price_m2, area_m2, ward_code, ptype, seen_at.
    Only priced observations with a price_m2; latest observation in the month wins."""
    q = ("SELECT o.listing_id, substr(o.seen_at,1,7) AS month, o.seen_at, o.price, o.price_m2, l.area_m2, l.ward_code, "
         "l.ptype FROM listing_obs o JOIN listing l ON l.id = o.listing_id "
         "WHERE o.kind = ? AND o.seen_at <= ? AND o.price IS NOT NULL AND o.price_m2 IS NOT NULL AND o.price_m2 > 0")
    args: list = [kind, _end(as_of)]
    if since:
        q += " AND o.seen_at >= ?"
        args.append(since)
    if ward_code:
        q += " AND l.ward_code = ?"
        args.append(ward_code)
    if ptype:
        q += " AND l.ptype = ?"
        args.append(ptype)
    q += " ORDER BY o.listing_id, o.seen_at"
    best: dict[tuple, dict] = {}
    for r in con.execute(q, args):
        best[(r["listing_id"], r["month"])] = dict(r)
    return list(best.values())


def ppm2_table(con: sqlite3.Connection, as_of: str, by: tuple[str, ...] = ("ward_code", "ptype"), kind: str = "asking",
               min_n: int = 5, since: str | None = None) -> list[dict]:
    """Monthly price per m² (VND/m²) by group: ``{<by...>, month, n, median, q1, q3, insufficient, reason}``.
    Groups with fewer than ``min_n`` listings that month keep their ``n`` but report ``median=None`` and
    ``insufficient=True`` — a thin median is not published as a number."""
    groups: dict[tuple, list[float]] = {}
    for r in monthly_obs(con, as_of, kind, since=since):
        key = tuple(r.get(b) for b in by) + (r["month"],)
        groups.setdefault(key, []).append(r["price_m2"])
    out = []
    for key in sorted(groups, key=lambda k: tuple("" if v is None else str(v) for v in k)):
        xs = groups[key]
        row = dict(zip(by, key[:-1]))
        row.update(month=key[-1], n=len(xs), kind=kind)
        if len(xs) < min_n:
            row.update(median=None, q1=None, q3=None, insufficient=True, reason=f"n={len(xs)} < min_n={min_n}")
        else:
            row.update(median=median(xs), q1=quantile(xs, 0.25), q3=quantile(xs, 0.75), insufficient=False, reason=None)
        out.append(row)
    return out


def _next_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y + (mo == 12)}-{1 if mo == 12 else mo + 1:02d}"


def repeat_index(con: sqlite3.Connection, as_of: str, ward_code: str | None = None, ptype: str | None = None,
                 kind: str = "asking", min_pairs: int = 3, changed_only: bool = False) -> dict | Insufficient:
    """Chain-linked same-listing index (base 100 at the first month).

    The link from month m−1 to m is the median log price ratio over listings priced in both months (same listing,
    so composition is held fixed). Unchanged prices are included by default — dropping them (``changed_only=True``)
    keeps only re-priced listings, which over-weights cuts. A link with fewer than ``min_pairs`` pairs breaks the
    chain: that month and every later one is ``None`` with the reason, never interpolated.
    Returns ``{method, kind, months: [{month, index, n_pairs, reason}]}`` or Insufficient when no link exists.
    """
    by_listing: dict[int, dict[str, float]] = {}
    for r in monthly_obs(con, as_of, kind, ward_code, ptype):
        by_listing.setdefault(r["listing_id"], {})[r["month"]] = r["price"]
    months = sorted({m for d in by_listing.values() for m in d})
    if len(months) < 2:
        return Insufficient("repeat_index", "fewer than two months of observations", {"months": months})
    first, last = months[0], months[-1]
    seq = [first]
    while seq[-1] < last:
        seq.append(_next_month(seq[-1]))
    out = [{"month": first, "index": 100.0, "n_pairs": None, "reason": None}]
    level: float | None = 100.0
    links = 0
    for prev, cur in zip(seq, seq[1:]):
        logs = [math.log(d[cur] / d[prev]) for d in by_listing.values()
                if prev in d and cur in d and d[prev] > 0 and d[cur] > 0 and (not changed_only or d[cur] != d[prev])]
        if level is None:
            out.append({"month": cur, "index": None, "n_pairs": len(logs), "reason": "chain broken earlier"})
            continue
        if len(logs) < min_pairs:
            level = None
            out.append({"month": cur, "index": None, "n_pairs": len(logs), "reason": f"pairs={len(logs)} < {min_pairs}"})
            continue
        level = level * math.exp(median(logs))
        links += 1
        out.append({"month": cur, "index": level, "n_pairs": len(logs), "reason": None})
    if links == 0:
        return Insufficient("repeat_index", f"no month link has >= {min_pairs} same-listing pairs", {"months": out})
    return {"method": "repeat_listing_chain", "kind": kind, "ward_code": ward_code, "ptype": ptype, "months": out}


def hedonic_index(con: sqlite3.Connection, as_of: str, kind: str = "asking", min_n: int = 30,
                  since: str | None = None) -> dict | Insufficient:
    """Time-dummy hedonic index: OLS of log(price/m²) on ward and ptype dummies, log(area) and month dummies.
    index(month) = 100 × exp(β_month), base = first month. Rows lacking ward or area are dropped (counted).
    Returns ``{method, kind, n, dropped, r2, sigma, months: [{month, index, n}], coef}`` or Insufficient."""
    data = monthly_obs(con, as_of, kind, since=since)
    usable = [r for r in data if r["ward_code"] and r["area_m2"] and r["area_m2"] > 0]
    dropped = len(data) - len(usable)
    if len(usable) < min_n:
        return Insufficient("hedonic_index", f"n={len(usable)} < min_n={min_n}", {"dropped": dropped})
    months = sorted({r["month"] for r in usable})
    wards = sorted({r["ward_code"] for r in usable})
    ptypes = sorted({r["ptype"] for r in usable})
    if len(months) < 2:
        return Insufficient("hedonic_index", "fewer than two months", {"months": months})
    names = ["const", "log_area"] + [f"ward:{w}" for w in wards[1:]] + [f"ptype:{p}" for p in ptypes[1:]] + \
            [f"month:{m}" for m in months[1:]]
    X, y = [], []
    for r in usable:
        row = [1.0, math.log(r["area_m2"])]
        row += [1.0 if r["ward_code"] == w else 0.0 for w in wards[1:]]
        row += [1.0 if r["ptype"] == p else 0.0 for p in ptypes[1:]]
        row += [1.0 if r["month"] == m else 0.0 for m in months[1:]]
        X.append(row)
        y.append(math.log(r["price_m2"]))
    res = ols(X, y, names)
    if res is None:
        return Insufficient("hedonic_index", "singular design (collinear dummies or too few rows per column)",
                            {"n": len(usable), "k": len(names)})
    coef = res.coef()
    counts = {m: sum(1 for r in usable if r["month"] == m) for m in months}
    out = [{"month": months[0], "index": 100.0, "n": counts[months[0]]}]
    out += [{"month": m, "index": 100.0 * math.exp(coef[f"month:{m}"]), "n": counts[m]} for m in months[1:]]
    return {"method": "hedonic_time_dummy", "kind": kind, "n": len(usable), "dropped": dropped, "r2": res.r2,
            "sigma": res.sigma, "months": out, "coef": coef}
