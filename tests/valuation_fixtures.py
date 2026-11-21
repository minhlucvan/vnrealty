"""Synthetic in-memory database helpers for the valuation / calibration tests. No network, no real records."""
from __future__ import annotations

import itertools

from vnrealty.store.db import connect

_ids = itertools.count(1)
OPEN: list = []


def close_all():
    """Close every connection made by db(); call from tearDownModule."""
    while OPEN:
        OPEN.pop().close()


def db():
    con = connect(":memory:")
    for code in ("w-a", "w-b", "w-c"):
        con.execute("INSERT INTO ward(code, name_vi) VALUES (?, ?)", (code, code.upper()))
    con.commit()
    OPEN.append(con)
    return con


def add_listing(con, *, ptype="land", ward="w-a", area=100.0, lat=None, lng=None, alley=4.0, corner=0, frontage=5.0,
                legal="so_hong", obs=(), deal="sale"):
    """obs: iterable of (seen_at, price, kind). Returns listing id."""
    n = next(_ids)
    first = min((o[0] for o in obs), default="2026-01-01")
    cur = con.execute(
        "INSERT INTO listing(fingerprint, ptype, deal, ward_code, lat, lng, area_m2, frontage_m, alley_m, corner, legal,"
        " first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"fp{n}", ptype, deal, ward, lat, lng, area, frontage, alley, corner, legal, first, first))
    lid = cur.lastrowid
    for i, (seen, price, kind) in enumerate(obs):
        con.execute("INSERT INTO listing_obs(listing_id, seen_at, site, url, kind, price, price_m2) VALUES (?,?,?,?,?,?,?)",
                    (lid, seen, f"site{i}", f"https://example.test/{lid}/{i}", kind, price,
                     price / area if price else None))
    con.commit()
    return lid


def add_sale(con, *, listing_id=None, sold_at="2026-06-01", price=5e9, ward="w-a", ptype="land", area=100.0):
    con.execute("INSERT INTO sale_evidence(listing_id, sold_at, price, ward_code, ptype, area_m2, source)"
                " VALUES (?,?,?,?,?,?,?)", (listing_id, sold_at, price, ward, ptype, area, "notary (synthetic)"))
    con.commit()
