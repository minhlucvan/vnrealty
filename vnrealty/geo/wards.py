"""Đà Nẵng commune-level units after the 1 July 2025 reform, and matching printed addresses to them.

Source data: ``reference/wards_da_nang.json`` (Nghị quyết 1659/NQ-UBTVQH15, 16 June 2025: districts abolished, Quảng
Nam merged into Đà Nẵng, 94 units). Each entry lists the pre-reform wards it was formed from, so a listing that still
prints "P. Hoà Quý, Q. Ngũ Hành Sơn" maps to the new ``ngu-hanh-son`` ward.

``match_ward`` never guesses: an old district that was split across several new wards ("Sơn Trà" alone) returns
``None``; ``match_ward_detail`` says why and lists the candidates.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from vnrealty.listings.parse import fold

__all__ = ["WARDS_PATH", "load_wards", "seed_wards", "match_ward", "match_ward_detail", "haversine_km", "cell"]

WARDS_PATH = Path(__file__).resolve().parents[2] / "reference" / "wards_da_nang.json"

_WARD_PREFIX = r"(?:phuong|p\.|p\b|xa|x\.|dac khu|thi tran|tt\.?)"
_DIST_PREFIX = r"(?:quan|q\.|q\b|huyen|h\.|thi xa|tx\.?|thanh pho|tp\.?)"
# common abbreviations for old districts
_DIST_ALIAS = {"nhs": "ngu hanh son", "q nhs": "ngu hanh son", "hc": "hai chau", "tk": "thanh khe", "lc": "lien chieu",
               "cl": "cam le", "hv": "hoa vang"}


def load_wards(path: str | Path | None = None) -> list[dict]:
    """The ward entries from the reference JSON (code, name_vi, kind, old_district(s), old_wards, lat/lng, verified)."""
    return _load(str(path or WARDS_PATH))["wards"]


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def seed_wards(con: sqlite3.Connection, path: str | Path | None = None) -> int:
    """Insert or refresh every ward into the ``ward`` table. Returns the number of rows written."""
    n = 0
    for w in load_wards(path):
        notes = {"kind": w.get("kind"), "verified": w.get("verified"), "old_districts": w.get("old_districts"),
                 "note": w.get("note")}
        con.execute(
            "INSERT INTO ward(code, name_vi, city, old_district, old_ward, lat, lng, notes) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(code) DO UPDATE SET name_vi=excluded.name_vi, old_district=excluded.old_district, "
            "old_ward=excluded.old_ward, lat=excluded.lat, lng=excluded.lng, notes=excluded.notes",
            (w["code"], w["name_vi"], "da-nang", w.get("old_district"), "; ".join(w.get("old_wards") or []),
             w.get("lat"), w.get("lng"), json.dumps(notes, ensure_ascii=False)))
        n += 1
    con.commit()
    return n


def _bare(name: str) -> str:
    """Folded name without unit prefix or the '(một phần)' style qualifiers."""
    f = fold(re.sub(r"\(.*?\)", "", name))
    f = re.sub(rf"^{_WARD_PREFIX}\s*|^{_DIST_PREFIX}\s*", "", f).strip(" .")
    return f


@lru_cache(maxsize=4)
def _index(path: str) -> dict:
    new: dict[str, str] = {}
    old: dict[str, set[str]] = {}
    dist: dict[str, set[str]] = {}
    for w in _load(path)["wards"]:
        new[_bare(w["name_vi"])] = w["code"]
        for o in w.get("old_wards") or []:
            if "toan bo" in fold(o):
                continue
            old.setdefault(_bare(o), set()).add(w["code"])
        for d in w.get("old_districts") or [w.get("old_district")]:
            if d:
                dist.setdefault(_bare(d), set()).add(w["code"])
    return {"new": new, "old": old, "dist": dist}


def _alias(s: str) -> str:
    return _DIST_ALIAS.get(s, s)


def match_ward_detail(text: str | None, path: str | Path | None = None) -> dict:
    """Match an address to a ward → ``{code, how, candidates, matched}``.

    ``how``: ``new_name`` | ``old_ward`` | ``old_district`` (district mapped to exactly one new unit) |
    ``ambiguous`` (several candidates, ``code`` is None) | ``none``. Segments are read most-specific first (left to
    right on a comma-separated address); a district segment narrows an ambiguous old ward name.
    """
    idx = _index(str(path or WARDS_PATH))
    out = {"code": None, "how": "none", "candidates": [], "matched": None}
    f = fold(text)
    if not f:
        return out
    segs = [s.strip(" .") for s in re.split(r"[,;|\n–]| - ", f) if s.strip(" .")]
    districts: set[str] | None = None
    for s in segs:
        name = _alias(_bare(s))
        prefixed_ward = bool(re.match(rf"^{_WARD_PREFIX}\s*\S", s))
        if name in idx["dist"] and not prefixed_ward:
            # "Q. Sơn Trà" or a bare "Sơn Trà": read as the old district (the conservative reading)
            districts = (districts or set()) | idx["dist"][name]
    ambiguous: list[str] = []

    def narrow(cands: set[str]) -> set[str]:
        if len(cands) > 1 and districts:
            return (cands & districts) or cands
        return cands

    for s in segs:
        is_ward = bool(re.match(rf"^{_WARD_PREFIX}\s*\S", s))
        if re.match(rf"^{_DIST_PREFIX}\s*\S", s):
            continue
        name = _alias(_bare(s))
        if name in idx["dist"] and not is_ward:
            continue
        cands: set[str] = set()
        if name in idx["new"]:
            cands.add(idx["new"][name])
        cands |= idx["old"].get(name, set())
        if not cands:
            continue
        how = "new_name" if name in idx["new"] and idx["new"][name] in narrow(cands) else "old_ward"
        cands = narrow(cands)
        if len(cands) == 1:
            code = next(iter(cands))
            how = "new_name" if idx["new"].get(name) == code else "old_ward"
            return {"code": code, "how": how, "candidates": [code], "matched": s}
        ambiguous = sorted(cands)
        break
    if not ambiguous:
        # free text: any known ward name as a whole phrase; earliest wins, longer wins a tie ("hòa khánh nam")
        hits = []
        for table in (idx["new"], idx["old"]):
            for name, codes in table.items():
                if len(name) < 4 or (name in idx["dist"] and not re.search(rf"{_WARD_PREFIX}\s*{re.escape(name)}", f)):
                    continue
                m = re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", f)
                if m:
                    hits.append((m.start(), -len(name), name, {codes} if isinstance(codes, str) else set(codes)))
        if hits:
            hits.sort(key=lambda h: (h[0], h[1]))
            _, _, name, _ = hits[0]
            codes = set().union(*(h[3] for h in hits if h[2] == name))
            codes = narrow(codes)
            if len(codes) == 1:
                code = next(iter(codes))
                return {"code": code, "how": "new_name" if idx["new"].get(name) == code else "old_ward",
                        "candidates": [code], "matched": name}
            ambiguous = sorted(codes)
    if not ambiguous and districts:
        if len(districts) == 1:
            c = next(iter(districts))
            return {"code": c, "how": "old_district", "candidates": [c], "matched": None}
        ambiguous = sorted(districts)
    if ambiguous:
        out.update(how="ambiguous", candidates=ambiguous)
    return out


def match_ward(text: str | None, path: str | Path | None = None) -> str | None:
    """Ward code for a printed address/ward string, or ``None`` when it cannot be placed unambiguously.
    Diacritic-insensitive: "Hòa Quý, Ngũ Hành Sơn", "P. Hoà Quý", "Phường Hải Châu" all work."""
    return match_ward_detail(text, path)["code"]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km (mean Earth radius 6371.0088 km)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def cell(lat: float, lng: float, m: float = 100.0) -> str:
    """A square grid cell id of side ≈ ``m`` metres (longitude scaled at the cell's latitude band), e.g. 'g100:…'."""
    dlat = m / 111_320.0
    i = math.floor(lat / dlat)
    dlng = m / (111_320.0 * max(math.cos(math.radians((i + 0.5) * dlat)), 1e-6))
    j = math.floor(lng / dlng)
    return f"g{int(m)}:{i}:{j}"
