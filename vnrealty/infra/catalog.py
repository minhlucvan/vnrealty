"""Catalogue of infrastructure, zoning and large private projects that can move land prices.

Projects live in the ``project`` table with citations in ``project_evidence``. ``p_done`` (chance of completion by
``done_year``) and ``uplift`` (fractional lift for land next to it) are desk judgement; their reasoning is kept in
``project.notes``.

**Notes convention.** ``project.notes`` holds a JSON object (not free text) with optional keys:

* ``basis`` — dict field → how it is known (``'sourced: …'`` or ``'judgement: …'``);
* ``zoning`` — ``{"codes": ["ODT", "DGT"], "source": url, "as_of": "YYYY-MM-DD", "note": "…"}`` — land-use codes
  from ``reference/landuse_codes.json`` (Thông tư 08/2024/TT-BTNMT), validated by :func:`zoning_note`;
* ``text`` — any free-text remark.

Units: km, VND, fractions, calendar years.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from vnrealty.store.db import REPO

__all__ = ["upsert_project", "add_evidence", "seed_projects", "near", "catalysts_for", "zoning_note",
           "parse_notes", "landuse_codes", "haversine_km"]

PROJECTS_PATH = REPO / "reference" / "projects_da_nang.json"
LANDUSE_PATH = REPO / "reference" / "landuse_codes.json"
COLS = ("name_vi", "name_en", "kind", "status", "lat", "lng", "radius_km", "ward_codes", "budget_vnd", "start_year",
        "done_year", "p_done", "uplift", "notes")


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two WGS84 points (degrees)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, a)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def landuse_codes(path: str | Path | None = None) -> dict:
    """Code → {group, vi, en} from ``reference/landuse_codes.json`` (cadastral codes only)."""
    with open(path or LANDUSE_PATH, encoding="utf-8") as fh:
        return json.load(fh)["codes"]


def zoning_note(codes: list[str], source: str, as_of: str, note: str | None = None) -> dict:
    """A validated ``zoning`` note. Raises ValueError for a code not in Thông tư 08/2024 Phụ lục II."""
    known = landuse_codes()
    bad = [c for c in codes if c.upper() not in known]
    if bad:
        raise ValueError(f"unknown land-use codes {bad}; planning-map symbols (e.g. CXK) are not cadastral codes")
    out = {"codes": [c.upper() for c in codes], "source": source, "as_of": as_of}
    if note:
        out["note"] = note
    return out


def parse_notes(notes: str | None) -> dict:
    """``project.notes`` as a dict (free text that is not JSON comes back as ``{'text': notes}``)."""
    if not notes:
        return {}
    try:
        v = json.loads(notes)
        return v if isinstance(v, dict) else {"text": notes}
    except ValueError:
        return {"text": notes}


def upsert_project(con: sqlite3.Connection, p: dict) -> str:
    """Insert or update a project by ``id``; returns the id. ``ward_codes`` may be a list; ``notes`` may be a dict
    (stored as JSON). Keys ``basis`` and ``zoning`` are folded into ``notes``. Fields absent from ``p`` are kept."""
    if not p.get("id"):
        raise ValueError("project needs an id")
    rec = {k: p[k] for k in COLS if k in p}
    exists = con.execute("SELECT notes FROM project WHERE id = ?", (p["id"],)).fetchone()
    notes = parse_notes(exists[0]) if exists else {}
    if "notes" in rec:
        notes.update(parse_notes(rec["notes"]) if isinstance(rec["notes"], str) else dict(rec["notes"] or {}))
    for k in ("basis", "zoning"):
        if k in p:
            notes[k] = p[k]
    if notes or "notes" in rec:
        rec["notes"] = json.dumps(notes, ensure_ascii=False, sort_keys=True)
    if isinstance(rec.get("ward_codes"), (list, tuple)):
        rec["ward_codes"] = json.dumps(list(rec["ward_codes"]), ensure_ascii=False)
    rec["updated_at"] = _now()
    if exists:
        sets = ", ".join(f"{k} = ?" for k in rec)
        con.execute(f"UPDATE project SET {sets} WHERE id = ?", (*rec.values(), p["id"]))
    else:
        cols = ["id", *rec]
        con.execute(f"INSERT INTO project({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", (p["id"], *rec.values()))
    con.commit()
    return p["id"]


def add_evidence(con: sqlite3.Connection, project_id: str, url: str, title: str | None = None,
                 published: str | None = None, claim: str | None = None, seen_at: str | None = None) -> int | None:
    """Attach a citation; returns its row id, or None when the same (project, url, claim) already exists."""
    if not url:
        raise ValueError("evidence needs a url")
    dup = con.execute("SELECT id FROM project_evidence WHERE project_id = ? AND url = ? AND COALESCE(claim, '') = ?",
                      (project_id, url, claim or "")).fetchone()
    if dup:
        return None
    cur = con.execute("INSERT INTO project_evidence(project_id, url, title, published, seen_at, claim) VALUES (?,?,?,?,?,?)",
                      (project_id, url, title, published, seen_at or _now(), claim))
    con.commit()
    return int(cur.lastrowid)


def seed_projects(con: sqlite3.Connection, path: str | Path | None = None) -> int:
    """Upsert every project in ``reference/projects_da_nang.json`` (or ``path``) with its evidence; returns the count.
    A project without at least one evidence url is refused (ValueError)."""
    with open(path or PROJECTS_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    n = 0
    for p in doc["projects"]:
        ev = p.get("evidence") or []
        if not any(e.get("url") for e in ev):
            raise ValueError(f"project {p.get('id')} has no citation")
        upsert_project(con, p)
        for e in ev:
            add_evidence(con, p["id"], e["url"], e.get("title"), e.get("published"), e.get("claim"))
        n += 1
    return n


def near(con: sqlite3.Connection, lat: float, lng: float, km: float) -> list[dict]:
    """Projects with coordinates within ``km`` of (lat, lng), nearest first, each with ``distance_km`` and
    ``evidence`` (list of url/title/claim). Projects without coordinates are never 'near' anything."""
    out = []
    for r in con.execute("SELECT * FROM project WHERE lat IS NOT NULL AND lng IS NOT NULL").fetchall():
        d = haversine_km(lat, lng, r["lat"], r["lng"])
        if d <= km:
            row = dict(r)
            row["distance_km"] = d
            row["notes"] = parse_notes(row.get("notes"))
            row["evidence"] = [dict(e) for e in con.execute(
                "SELECT url, title, published, claim FROM project_evidence WHERE project_id = ? ORDER BY id", (r["id"],))]
            out.append(row)
    return sorted(out, key=lambda x: x["distance_km"])


def catalysts_for(con: sqlite3.Connection, lat: float, lng: float, km: float) -> dict:
    """Catalyst dicts for :func:`vnrealty.projection.catalysts.paths` from projects within ``km``.

    Returns ``{"catalysts": [{id, p, uplift, year, distance_km, decay_km, name}], "skipped": [{id, reason}]}``.
    Done or cancelled projects, and ones missing p_done / uplift / done_year, are skipped with the reason — a missing
    judgement is not defaulted. ``decay_km`` is the project's ``radius_km`` (None = no decay).
    """
    cats, skipped = [], []
    for r in near(con, lat, lng, km):
        if r["status"] in ("done", "cancelled"):
            skipped.append({"id": r["id"], "reason": f"status {r['status']}: no forward catalyst"})
            continue
        missing = [k for k in ("p_done", "uplift", "done_year") if r.get(k) is None]
        if missing:
            skipped.append({"id": r["id"], "reason": f"missing {', '.join(missing)}"})
            continue
        cats.append({"id": r["id"], "name": r["name_en"] or r["name_vi"], "p": r["p_done"], "uplift": r["uplift"],
                     "year": r["done_year"], "distance_km": r["distance_km"], "decay_km": r["radius_km"],
                     "basis": r["notes"].get("basis")})
    return {"catalysts": cats, "skipped": skipped}
