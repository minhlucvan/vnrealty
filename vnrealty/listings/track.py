"""Listing tracking: price history, changes over a window, saved searches and conservative 'gone' marking.

Price changes are computed per (listing, site) series, so the same property quoted at two prices on two sites never
shows up as a cut or a raise. Everything that takes ``as_of`` reads only observations with ``seen_at <= as_of``.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from vnrealty.store.db import rows

__all__ = ["history", "changes", "mark_gone", "add_search", "list_searches", "touch_search", "RELIST_GAP_DAYS"]

RELIST_GAP_DAYS = 30


def _day(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def _end(as_of: str) -> str:
    """Inclusive upper bound: a bare date covers the whole day."""
    return as_of + "T99" if len(as_of) == 10 else as_of


def history(con: sqlite3.Connection, listing_id: int) -> list[dict]:
    """Every observation of a listing, oldest first: seen_at, site, kind, price (VND), price_m2, url, raw_ref."""
    return rows(con, "SELECT seen_at, site, site_id, kind, price, price_m2, url, posted_at, raw_ref FROM listing_obs "
                     "WHERE listing_id = ? ORDER BY seen_at, site", (listing_id,))


def changes(con: sqlite3.Connection, since: str, as_of: str, gap_days: int = RELIST_GAP_DAYS) -> dict:
    """What happened in (since, as_of]:

    * ``cuts`` / ``raises`` — consecutive priced observations on the same site whose later one falls in the window:
      ``{listing_id, site, at, from, to, vnd, pct}`` (vnd = to − from, pct as a fraction);
    * ``new`` — listings whose first observation is in the window;
    * ``relisted`` — listings observed in the window after a silence of more than ``gap_days`` days.
    """
    obs = rows(con, "SELECT listing_id, site, seen_at, kind, price FROM listing_obs WHERE seen_at <= ? "
                    "ORDER BY listing_id, seen_at", (_end(as_of),))
    lo = _end(since)
    cuts, raises, new, relisted = [], [], [], []
    by_listing: dict[int, list[dict]] = {}
    for o in obs:
        by_listing.setdefault(o["listing_id"], []).append(o)
    for lid, series in by_listing.items():
        if series[0]["seen_at"] > lo:
            new.append(lid)
        else:
            for prev, cur in zip(series, series[1:]):
                if cur["seen_at"] > lo and (_day(cur["seen_at"]) - _day(prev["seen_at"])).days > gap_days:
                    relisted.append(lid)
                    break
        last: dict[tuple, dict] = {}
        for o in series:
            if o["price"] is None:
                continue
            key = (o["site"], o["kind"])
            p = last.get(key)
            if p is not None and o["seen_at"] > lo and o["price"] != p["price"]:
                ev = {"listing_id": lid, "site": o["site"], "at": o["seen_at"], "from": p["price"], "to": o["price"],
                      "vnd": o["price"] - p["price"], "pct": (o["price"] - p["price"]) / p["price"] if p["price"] else None}
                (cuts if o["price"] < p["price"] else raises).append(ev)
            last[key] = o
    return {"since": since, "as_of": as_of, "cuts": cuts, "raises": raises, "new": new, "relisted": relisted}


def add_search(con: sqlite3.Connection, name: str, site: str, url: str, criteria: dict | None = None) -> int:
    """Save (or update) a named search the tracker re-runs. Returns its id."""
    con.execute("INSERT INTO search(name, site, url, criteria) VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                "site=excluded.site, url=excluded.url, criteria=excluded.criteria",
                (name, site, url, json.dumps(criteria or {}, ensure_ascii=False, sort_keys=True)))
    con.commit()
    return con.execute("SELECT id FROM search WHERE name = ?", (name,)).fetchone()[0]


def list_searches(con: sqlite3.Connection) -> list[dict]:
    """All saved searches with criteria decoded."""
    out = rows(con, "SELECT id, name, site, url, criteria, last_run FROM search ORDER BY name")
    for r in out:
        r["criteria"] = json.loads(r["criteria"] or "{}")
    return out


def touch_search(con: sqlite3.Connection, name: str, at: str) -> None:
    """Record that a saved search was re-run (captured completely) at ``at``. KeyError for an unknown name."""
    cur = con.execute("UPDATE search SET last_run = ? WHERE name = ?", (at, name))
    if not cur.rowcount:
        raise KeyError(name)
    con.commit()


def mark_gone(con: sqlite3.Connection, as_of: str, days: int = 30) -> list[int]:
    """Mark listings ``gone`` — conservatively. A listing is gone only when ALL hold:

    * it was captured through a saved search (an observation whose ``extra.search`` names it — set by the
      ``# search:`` header or the capture's ``search`` key);
    * that search has been re-run (``last_run``) after the listing was last seen, and ``last_run <= as_of``;
    * the listing has not been seen for more than ``days`` days before ``as_of``.

    Listings found any other way (one-off pages, social posts) are never marked gone: not seeing them again says
    nothing. Returns the ids marked. A gone listing seen again is re-activated by ingest.
    """
    searches = {r["name"]: r["last_run"] for r in rows(con, "SELECT name, last_run FROM search WHERE last_run IS NOT NULL")}
    if not searches:
        return []
    cutoff = (_day(as_of) - dt.timedelta(days=days)).isoformat()
    cand = rows(con, "SELECT l.id, l.last_seen, o.extra FROM listing l JOIN listing_obs o ON o.listing_id = l.id "
                     "WHERE l.status = 'active' AND l.last_seen < ? AND o.seen_at <= ?", (cutoff, _end(as_of)))
    gone: list[int] = []
    for r in cand:
        if r["id"] in gone:
            continue
        try:
            s = (json.loads(r["extra"] or "{}") or {}).get("search")
        except json.JSONDecodeError:
            continue
        run = searches.get(s)
        if run and run <= _end(as_of) and run > r["last_seen"]:
            gone.append(r["id"])
    for lid in gone:
        con.execute("UPDATE listing SET status = 'gone' WHERE id = ?", (lid,))
    con.commit()
    return gone
