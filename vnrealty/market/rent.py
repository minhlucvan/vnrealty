"""Rents and gross yields from listings. Both sides are ASKING (rent asked, sale asked), so the result is an
*asking gross yield* — before vacancy, costs, tax and the asking→sale haircut. Point in time on ``seen_at``.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from vnrealty.stats import median, quantile
from vnrealty.types import Insufficient

__all__ = ["rent_ppm2", "gross_yield"]


def _latest(con: sqlite3.Connection, kind: str, ward: str | None, ptype: str | None, as_of: str | None,
            window_days: int) -> list[dict]:
    q = ("SELECT o.listing_id, o.seen_at, o.price, o.price_m2 FROM listing_obs o JOIN listing l ON l.id = o.listing_id "
         "WHERE o.kind = ? AND o.price IS NOT NULL")
    args: list = [kind]
    if as_of:
        q += " AND o.seen_at <= ? AND o.seen_at >= ?"
        args += [as_of + "T99" if len(as_of) == 10 else as_of,
                 (dt.date.fromisoformat(as_of[:10]) - dt.timedelta(days=window_days)).isoformat()]
    if ward:
        q += " AND l.ward_code = ?"
        args.append(ward)
    if ptype:
        q += " AND l.ptype = ?"
        args.append(ptype)
    last: dict[int, dict] = {}
    for r in con.execute(q + " ORDER BY o.seen_at", args):
        last[r["listing_id"]] = dict(r)
    return list(last.values())


def rent_ppm2(con: sqlite3.Connection, ward: str | None, ptype: str | None, as_of: str | None = None,
              window_days: int = 180, min_n: int = 5) -> dict | Insufficient:
    """Monthly asking rent per m² (VND/m²/month): ``{n, median, q1, q3, median_rent}`` over each rental listing's
    latest sighting in the window. ``as_of=None`` reads every observation (no window)."""
    rs = _latest(con, "rent", ward, ptype, as_of, window_days)
    pm = [r["price_m2"] for r in rs if r["price_m2"]]
    if len(pm) < min_n:
        return Insufficient("rent_ppm2", f"n={len(pm)} < {min_n}", {"n": len(pm), "ward": ward, "ptype": ptype})
    return {"n": len(pm), "median": median(pm), "q1": quantile(pm, 0.25), "q3": quantile(pm, 0.75),
            "median_rent": median([r["price"] for r in rs])}


def gross_yield(con: sqlite3.Connection, ward: str | None, ptype: str | None, as_of: str | None = None,
                basis: str = "m2", window_days: int = 180, min_n: int = 5) -> dict | Insufficient:
    """Asking gross yield = 12 × median monthly rent / median sale asking, as a fraction.

    ``basis='m2'`` (default) divides medians of price per m² on each side, which is robust to the two samples having
    different unit sizes; ``basis='total'`` uses medians of whole prices. Reports ``n_rent``/``n_sale``.
    Insufficient when either side has fewer than ``min_n`` listings.
    """
    if basis not in ("m2", "total"):
        raise ValueError("basis must be 'm2' or 'total'")
    key = "price_m2" if basis == "m2" else "price"
    rent = [r[key] for r in _latest(con, "rent", ward, ptype, as_of, window_days) if r[key]]
    sale = [r[key] for r in _latest(con, "asking", ward, ptype, as_of, window_days) if r[key]]
    if len(rent) < min_n or len(sale) < min_n:
        return Insufficient("gross_yield", f"n_rent={len(rent)}, n_sale={len(sale)}; need >= {min_n} each",
                            {"n_rent": len(rent), "n_sale": len(sale), "ward": ward, "ptype": ptype})
    mr, ms = median(rent), median(sale)
    return {"method": "asking_gross_yield", "basis": basis, "yield": 12 * mr / ms, "median_rent": mr, "median_sale": ms,
            "n_rent": len(rent), "n_sale": len(sale), "ward": ward, "ptype": ptype, "as_of": as_of}
