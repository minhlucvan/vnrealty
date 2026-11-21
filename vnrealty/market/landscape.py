"""Market landscape from listing observations: supply, monthly flow, days on market, price cuts, dispersion, and a
``summary`` whose notes are built only from the numbers computed here.

Point in time throughout: observations with ``seen_at <= as_of``; the ``listing.status`` column (which is current,
not historical) is never read. 'Active' = observed within ``active_days`` before ``as_of``. 'Gone' = last observed
more than ``gone_days`` before ``as_of`` — it is inferred from silence, so it is only as good as capture coverage.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from vnrealty.stats import median, quantile, mad
from vnrealty.types import Insufficient

__all__ = ["supply", "flow", "days_on_market", "price_cuts", "dispersion", "summary"]


def _end(as_of: str) -> str:
    return as_of + "T99" if len(as_of) == 10 else as_of


def _day(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def _series(con: sqlite3.Connection, as_of: str, ward_code: str | None, ptype: str | None, deal: str) -> dict[int, list[dict]]:
    q = ("SELECT o.listing_id, o.seen_at, o.site, o.kind, o.price, o.price_m2, l.ptype, l.ward_code FROM listing_obs o "
         "JOIN listing l ON l.id = o.listing_id WHERE o.seen_at <= ? AND l.deal = ?")
    args: list = [_end(as_of), deal]
    if ward_code:
        q += " AND l.ward_code = ?"
        args.append(ward_code)
    if ptype:
        q += " AND l.ptype = ?"
        args.append(ptype)
    out: dict[int, list[dict]] = {}
    for r in con.execute(q + " ORDER BY o.listing_id, o.seen_at", args):
        out.setdefault(r["listing_id"], []).append(dict(r))
    return out


def supply(con: sqlite3.Connection, as_of: str, ward_code: str | None = None, ptype: str | None = None,
           deal: str = "sale", active_days: int = 30) -> dict:
    """Active listings: observed within ``active_days`` before ``as_of`` → ``{n, by_ptype, active_days}``."""
    lo = (_day(as_of) - dt.timedelta(days=active_days)).isoformat()
    by: dict[str, int] = {}
    for lid, s in _series(con, as_of, ward_code, ptype, deal).items():
        if s[-1]["seen_at"] >= lo:
            by[s[-1]["ptype"]] = by.get(s[-1]["ptype"], 0) + 1
    return {"n": sum(by.values()), "by_ptype": by, "active_days": active_days, "as_of": as_of}


def _month_add(m: str, k: int) -> str:
    y, mo = int(m[:4]), int(m[5:7]) - 1 + k
    return f"{y + mo // 12}-{mo % 12 + 1:02d}"


def flow(con: sqlite3.Connection, as_of: str, months: int = 12, ward_code: str | None = None, ptype: str | None = None,
         deal: str = "sale", gone_days: int = 30, gap_days: int = 30) -> list[dict]:
    """Monthly ``{month, new, gone, relisted}``. ``gone`` counts listings whose last sighting fell in the month and
    who stayed unseen for ``gone_days`` — only decidable when that window has closed by ``as_of`` (else
    ``gone=None`` for the month). ``relisted`` = seen again after a silence of more than ``gap_days``."""
    end_month = as_of[:7]
    ms = [_month_add(end_month, -k) for k in range(months - 1, -1, -1)]
    rec = {m: {"month": m, "new": 0, "gone": 0, "relisted": 0} for m in ms}
    asof_d = _day(as_of)
    for lid, s in _series(con, as_of, ward_code, ptype, deal).items():
        first_m = s[0]["seen_at"][:7]
        if first_m in rec:
            rec[first_m]["new"] += 1
        last = _day(s[-1]["seen_at"])
        if (asof_d - last).days > gone_days and s[-1]["seen_at"][:7] in rec:
            rec[s[-1]["seen_at"][:7]]["gone"] += 1
        for a, b in zip(s, s[1:]):
            if (_day(b["seen_at"]) - _day(a["seen_at"])).days > gap_days and b["seen_at"][:7] in rec:
                rec[b["seen_at"][:7]]["relisted"] += 1
    for m in ms:
        y, mo = int(m[:4]), int(m[5:7])
        month_end = dt.date(y + (mo == 12), 1 if mo == 12 else mo + 1, 1) - dt.timedelta(days=1)
        if (asof_d - month_end).days <= gone_days:
            rec[m]["gone"] = None
    return [rec[m] for m in ms]


def days_on_market(con: sqlite3.Connection, as_of: str, ward_code: str | None = None, ptype: str | None = None,
                   deal: str = "sale", gone_days: int = 30, min_n: int = 5) -> dict | Insufficient:
    """Days between first and last sighting. ``completed`` = listings gone (unseen > ``gone_days``); ``active`` are
    right-censored (still listed, so their spell is a lower bound). Median of completed spells is the headline."""
    asof_d = _day(as_of)
    done, active = [], []
    for s in _series(con, as_of, ward_code, ptype, deal).values():
        d = (_day(s[-1]["seen_at"]) - _day(s[0]["seen_at"])).days
        ((done if (asof_d - _day(s[-1]["seen_at"])).days > gone_days else active)).append(d)
    if len(done) < min_n:
        return Insufficient("days_on_market", f"completed spells n={len(done)} < {min_n}",
                            {"n_completed": len(done), "n_active": len(active)})
    return {"median_completed": median(done), "q1": quantile(done, 0.25), "q3": quantile(done, 0.75),
            "n_completed": len(done), "median_active_censored": median(active), "n_active": len(active)}


def price_cuts(con: sqlite3.Connection, as_of: str, window_days: int = 90, ward_code: str | None = None,
               ptype: str | None = None, deal: str = "sale", min_n: int = 5) -> dict | Insufficient:
    """Among listings re-observed with a price on the same site within the window: share with ≥1 cut and the median
    cut (fraction, negative). Cross-site price gaps are not cuts."""
    lo = (_day(as_of) - dt.timedelta(days=window_days)).isoformat()
    eligible, cut_listings, cuts = 0, 0, []
    for s in _series(con, as_of, ward_code, ptype, deal).values():
        last: dict[str, float] = {}
        pairs, own = 0, []
        for o in s:
            if o["price"] is None:
                continue
            p = last.get(o["site"])
            if p is not None and o["seen_at"] >= lo:
                pairs += 1
                if o["price"] < p:
                    own.append((o["price"] - p) / p)
            last[o["site"]] = o["price"]
        if pairs:
            eligible += 1
            if own:
                cut_listings += 1
                cuts.extend(own)
    if eligible < min_n:
        return Insufficient("price_cuts", f"re-observed listings n={eligible} < {min_n}", {"n": eligible})
    return {"n": eligible, "n_cut": cut_listings, "cut_rate": cut_listings / eligible,
            "median_cut": median(cuts) if cuts else None, "window_days": window_days}


def dispersion(con: sqlite3.Connection, as_of: str, window_days: int = 90, ward_code: str | None = None,
               ptype: str | None = None, deal: str = "sale", min_n: int = 5) -> dict | Insufficient:
    """Spread of price/m² over listings' latest priced sighting in the window: median, IQR, IQR/median, MAD/median."""
    lo = (_day(as_of) - dt.timedelta(days=window_days)).isoformat()
    xs = []
    for s in _series(con, as_of, ward_code, ptype, deal).values():
        pm = [o["price_m2"] for o in s if o["price_m2"] and o["seen_at"] >= lo]
        if pm:
            xs.append(pm[-1])
    if len(xs) < min_n:
        return Insufficient("dispersion", f"n={len(xs)} < {min_n}", {"n": len(xs)})
    m, q1, q3 = median(xs), quantile(xs, 0.25), quantile(xs, 0.75)
    return {"n": len(xs), "median_m2": m, "q1": q1, "q3": q3, "iqr_ratio": (q3 - q1) / m if m else None,
            "mad_ratio": mad(xs) / m if m else None}


def summary(con: sqlite3.Connection, as_of: str, ward: str | None = None, ptype: str | None = None,
            deal: str = "sale") -> dict:
    """All landscape measures for a ward/ptype plus ``notes`` — sentences formatted from the computed numbers only
    (an Insufficient measure produces a note saying so, never a substitute)."""
    sup = supply(con, as_of, ward, ptype, deal)
    fl = flow(con, as_of, 6, ward, ptype, deal)
    dom = days_on_market(con, as_of, ward, ptype, deal)
    cuts = price_cuts(con, as_of, 90, ward, ptype, deal)
    disp = dispersion(con, as_of, 90, ward, ptype, deal)
    notes = [f"{sup['n']} active {deal} listings (seen in the last {sup['active_days']} days)."]
    last = fl[-1] if fl else None
    if last:
        notes.append(f"{last['month']}: {last['new']} new, {last['relisted']} relisted"
                     + (f", {last['gone']} gone." if last["gone"] is not None else "; gone not yet decidable."))
    for name, v in (("days on market", dom), ("price cuts", cuts), ("dispersion", disp)):
        if isinstance(v, Insufficient):
            notes.append(f"{name}: insufficient ({v.reason}).")
    if not isinstance(dom, Insufficient):
        notes.append(f"Median days on market {dom['median_completed']:.0f} (n={dom['n_completed']} completed spells).")
    if not isinstance(cuts, Insufficient):
        mc = f", median cut {cuts['median_cut'] * 100:.1f}%" if cuts["median_cut"] is not None else ""
        notes.append(f"{cuts['cut_rate'] * 100:.0f}% of {cuts['n']} re-observed listings cut price in 90 days{mc}.")
    if not isinstance(disp, Insufficient):
        notes.append(f"Median asking {disp['median_m2'] / 1e6:.1f} M VND/m² (IQR {disp['q1'] / 1e6:.1f}–"
                     f"{disp['q3'] / 1e6:.1f}, n={disp['n']}).")

    def j(v):
        return {"insufficient": v.reason, **v.detail} if isinstance(v, Insufficient) else v

    return {"as_of": as_of, "ward_code": ward, "ptype": ptype, "deal": deal, "kind": "asking" if deal == "sale" else "rent",
            "supply": sup, "flow": fl, "days_on_market": j(dom), "price_cuts": j(cuts), "dispersion": j(disp),
            "notes": notes}
