"""Store ListingObs: upsert the listing identity, append the price observation.

* A listing is found by (site, site_id) in ``listing_obs`` first, then by ``dedupe.fingerprint``; otherwise created.
* An existing listing keeps ``first_seen``; ``last_seen`` moves forward only; blank attributes are filled, never
  overwritten (the first site to state a value keeps it); a ``gone`` listing seen again becomes ``active``.
* Every sighting is one ``listing_obs`` row (``price`` may be NULL for "thỏa thuận"); ``price_m2`` = price / area.
* ``raw_ref`` is the saved capture path — the citation for the number.

Captures: ``.json`` from the browser scripts (``vnrealty.browser``) and ``.txt`` text captures with ``# url/site/
seen_at/kind/deal`` headers. Zoning and map captures carry no listings and are skipped (counted in ``skipped``).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from vnrealty.geo.wards import match_ward, seed_wards
from vnrealty.listings import sources
from vnrealty.listings.dedupe import extract_street, fingerprint
from vnrealty.listings.sources._common import read_text_capture
from vnrealty.types import ListingObs

__all__ = ["ingest", "ingest_file", "ingest_dir", "load_capture"]

_FILL = ("title", "address", "street", "ward_code", "lat", "lng", "area_m2", "floor_area_m2", "frontage_m", "depth_m",
         "alley_m", "floors", "bedrooms", "corner", "direction", "legal")


def _known_wards(con: sqlite3.Connection) -> set[str]:
    codes = {r[0] for r in con.execute("SELECT code FROM ward")}
    if not codes:
        seed_wards(con)
        codes = {r[0] for r in con.execute("SELECT code FROM ward")}
    return codes


def _find_listing(con: sqlite3.Connection, obs: ListingObs, fp: str) -> sqlite3.Row | None:
    if obs.site_id:
        r = con.execute("SELECT l.* FROM listing_obs o JOIN listing l ON l.id = o.listing_id "
                        "WHERE o.site = ? AND o.site_id = ? ORDER BY o.seen_at DESC LIMIT 1", (obs.site, obs.site_id)).fetchone()
        if r:
            return r
    return con.execute("SELECT * FROM listing WHERE fingerprint = ?", (fp,)).fetchone()


def _same_site_conflict(con: sqlite3.Connection, row: sqlite3.Row, obs: ListingObs) -> bool:
    """True when the fingerprint matched a listing that the SAME site already carries under a DIFFERENT ad id.
    Sites like nhatot place unpinned ads at shared approximate coordinates, so two 100 m² lots at one point would
    otherwise merge. Cross-site matches (the same lot on two sites) still merge."""
    if not obs.site_id:
        return False
    r = con.execute("SELECT 1 FROM listing_obs WHERE listing_id = ? AND site = ? AND site_id IS NOT NULL AND site_id != ? LIMIT 1",
                    (row["id"], obs.site, obs.site_id)).fetchone()
    return r is not None


def ingest(con: sqlite3.Connection, obs_list: list[ListingObs], raw_ref: str | None = None) -> dict:
    """Store observations → ``{new_listings, new_obs, updated, duplicate_obs}``. Commits once at the end."""
    wards = _known_wards(con)
    stats = {"new_listings": 0, "new_obs": 0, "updated": 0, "duplicate_obs": 0}
    for obs in obs_list:
        if obs.ward_code is None:
            obs.ward_code = match_ward(obs.ward_raw) or match_ward(obs.address)
        if obs.ward_code not in wards:
            if obs.ward_code is not None:
                obs.extra.setdefault("unmatched_ward_code", obs.ward_code)
            obs.ward_code = None
        if obs.street is None:
            obs.street = extract_street(obs.address)
        deal = "rent" if obs.kind == "rent" else "sale"
        fp = fingerprint(obs)
        row = _find_listing(con, obs, fp)
        if row is not None and row["fingerprint"] == fp and _same_site_conflict(con, row, obs):
            fp, row = f"site:{obs.site}:{obs.site_id}", None
            row = con.execute("SELECT * FROM listing WHERE fingerprint = ?", (fp,)).fetchone()
        attrs = {k: getattr(obs, k) for k in _FILL}
        if attrs["corner"] is not None:
            attrs["corner"] = int(attrs["corner"])
        if attrs["legal"] == "unknown":
            attrs["legal"] = None
        if row is None:
            cols = ["fingerprint", "ptype", "deal", "first_seen", "last_seen", "status"] + list(attrs)
            vals = [fp, obs.ptype, deal, obs.seen_at, obs.seen_at, "active"] + list(attrs.values())
            cur = con.execute(f"INSERT INTO listing({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
            lid = cur.lastrowid
            stats["new_listings"] += 1
        else:
            lid = row["id"]
            sets, args = [], []
            for k, v in attrs.items():
                if v is not None and row[k] is None:
                    sets.append(f"{k} = ?")
                    args.append(v)
            if row["ptype"] == "other" and obs.ptype != "other":
                sets.append("ptype = ?")
                args.append(obs.ptype)
            if obs.seen_at > row["last_seen"]:
                sets.append("last_seen = ?")
                args.append(obs.seen_at)
                if row["status"] == "gone":
                    sets.append("status = 'active'")
            if obs.seen_at < row["first_seen"]:
                sets.append("first_seen = ?")
                args.append(obs.seen_at)
            if sets:
                con.execute(f"UPDATE listing SET {', '.join(sets)} WHERE id = ?", args + [lid])
            stats["updated"] += 1
        price_m2 = obs.price_m2
        if price_m2 is None and obs.price is not None and obs.area_m2:
            price_m2 = obs.price / obs.area_m2
        cur = con.execute(
            "INSERT OR IGNORE INTO listing_obs(listing_id, seen_at, site, url, site_id, kind, price, price_m2, posted_at, "
            "raw_ref, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (lid, obs.seen_at, obs.site, obs.url, obs.site_id, obs.kind, obs.price, price_m2, obs.posted_at,
             raw_ref or obs.raw_ref, json.dumps(obs.extra, ensure_ascii=False, sort_keys=True, default=str)))
        if cur.rowcount:
            stats["new_obs"] += 1
        else:
            stats["duplicate_obs"] += 1
    con.commit()
    return stats


def load_capture(path: str | Path) -> list[ListingObs]:
    """Parse one capture file (.json or .txt) into ListingObs, each with ``raw_ref`` set to the path."""
    p = Path(path)
    if p.suffix == ".json":
        obs = sources.from_capture(json.loads(p.read_text(encoding="utf-8")))
    elif p.suffix == ".txt" and p.read_text(encoding="utf-8").startswith("#total="):
        from vnrealty.listings.sources import chotot
        obs = chotot.from_rows(p.read_text(encoding="utf-8"))
    elif p.suffix == ".txt":
        headers, text = read_text_capture(p)
        if (headers.get("kind") or "detail").lower() not in ("detail", "search", "social"):
            return []
        obs = sources.parse(headers, text)
    else:
        raise ValueError(f"unsupported capture type: {p.suffix}")
    for o in obs:
        o.raw_ref = str(p)
    return obs


def ingest_file(con: sqlite3.Connection, path: str | Path) -> dict:
    """Parse and store one capture file. Returns ingest stats plus ``parsed``."""
    obs = load_capture(path)
    s = ingest(con, obs, str(path))
    s["parsed"] = len(obs)
    return s


def ingest_dir(con: sqlite3.Connection, root: str | Path) -> dict:
    """Ingest every .json/.txt capture under ``root`` (sorted, so re-runs are deterministic). Re-ingesting a file
    adds nothing (observations are unique per listing/site/seen_at). Returns summed stats and ``files``/``errors``."""
    tot = {"files": 0, "parsed": 0, "new_listings": 0, "new_obs": 0, "updated": 0, "duplicate_obs": 0, "errors": []}
    for p in sorted(Path(root).rglob("*")):
        if p.suffix not in (".json", ".txt") or not p.is_file():
            continue
        try:
            s = ingest_file(con, p)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
            tot["errors"].append(f"{p}: {e}")
            continue
        tot["files"] += 1
        for k in ("parsed", "new_listings", "new_obs", "updated", "duplicate_obs"):
            tot[k] += s[k]
    return tot
