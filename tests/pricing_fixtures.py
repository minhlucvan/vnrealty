"""Synthetic in-memory database helpers for the pricing tests. No network, no real records."""
from __future__ import annotations

import itertools
import json

from vnrealty.store.db import connect

_ids = itertools.count(1)
OPEN: list = []


def close_all():
    while OPEN:
        OPEN.pop().close()


def db():
    """Three wards: w-a and w-b share old district D1, w-c is in D2."""
    con = connect(":memory:")
    for code, od in (("w-a", "D1"), ("w-b", "D1"), ("w-c", "D2")):
        con.execute("INSERT INTO ward(code, name_vi, old_district) VALUES (?,?,?)", (code, code.upper(), od))
    con.commit()
    OPEN.append(con)
    return con


def add(con, *, ptype="land", ward="w-a", area=100.0, deal="sale", obs=(("2026-10-01", 5e9),), alley=3.0,
        frontage=5.0, floor_area=None, bedrooms=None, legal="so_hong", title=None, street=None, status="active",
        extra=None):
    """obs: iterable of (seen_at, price) — price None means 'thỏa thuận'. Returns the listing id."""
    n = next(_ids)
    dates = [o[0] for o in obs] or ["2026-01-01"]
    cur = con.execute(
        "INSERT INTO listing(fingerprint, ptype, deal, ward_code, area_m2, floor_area_m2, frontage_m, alley_m, bedrooms,"
        " legal, title, street, first_seen, last_seen, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"pf{n}", ptype, deal, ward, area, floor_area, frontage, alley, bedrooms, legal, title, street, min(dates),
         max(dates), status))
    lid = cur.lastrowid
    kind = "rent" if deal == "rent" else "asking"
    for i, (seen, price) in enumerate(obs):
        con.execute("INSERT INTO listing_obs(listing_id, seen_at, site, url, kind, price, extra) VALUES (?,?,?,?,?,?,?)",
                    (lid, seen, f"site{i}", f"https://example.test/{lid}/{i}", kind, price,
                     json.dumps(extra) if extra else None))
    con.commit()
    return lid


def spread(con, n, *, ptype="land", ward="w-a", area=100.0, lo=40e6, hi=60e6, unit="m2", deal="sale", **kw):
    """n listings whose unit price runs evenly from lo to hi (per m² of ``area`` unless unit='abs')."""
    ids = []
    for i in range(n):
        u = lo + (hi - lo) * i / max(1, n - 1)
        price = u * area if unit == "m2" else u
        ids.append(add(con, ptype=ptype, ward=ward, area=area, deal=deal, obs=(("2026-10-01", price),), **kw))
    return ids
