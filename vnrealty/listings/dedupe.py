"""Identity of a listed property across re-captures and across sites.

Two keys, used in this order by ``ingest``:

1. **Same site, same site_id** → the same listing (looked up in ``listing_obs``; see ``ingest._find_listing``).
2. **Attribute fingerprint** (``fingerprint``) → the same physical property even when two sites print different
   prices: location (a ~100 m geo cell when lat/lng are known, else folded street + post-2025 ward code), area to
   1 m², frontage to 0.1 m, ptype and deal. Price is deliberately NOT part of it. The ward is the NEW unit so an
   old-name and a new-name address agree; two lots on one street inside one merged ward with the same area,
   frontage and type would collide — accepted, since that is rare and the site_id key still separates re-captures.
   Known miss: a geo cell boundary between two sites' coordinates, or one site giving coordinates and the other
   only a street, yields two listings (a false split, never a false merge).

When an observation has no location or no area the attribute fingerprint would merge unrelated listings, so the
fingerprint falls back to ``site:<site>:<site_id>`` (or the URL, or a hash of title+address) — never to a collision.
"""
from __future__ import annotations

import hashlib
import re

from vnrealty.geo.wards import cell, match_ward
from vnrealty.listings.parse import fold
from vnrealty.types import ListingObs

__all__ = ["fingerprint", "extract_street", "GEO_CELL_M"]

GEO_CELL_M = 100.0


def extract_street(address: str | None) -> str | None:
    """Folded street name from an address ("K12/3 Lê Văn Hiến, Hòa Quý" → 'le van hien'). ``None`` when the first
    segment is only a ward/district/city name or holds no letters."""
    if not address:
        return None
    for seg in re.split(r"[,;]", address):
        f = fold(seg)
        if not f:
            continue
        if re.match(r"^(phuong|p\.|xa|quan|q\.|huyen|tp|thanh pho|da nang|quang nam|viet nam)\b", f):
            return None
        if match_ward(seg) and not re.search(r"\d", f) and len(f.split()) <= 4 and not re.match(r"^(duong|pho)\b", f):
            return None
        prev = None
        while prev != f:          # house numbers and lane prefixes: "123", "K12/3", "kiệt 45", "số nhà 7"
            prev = f
            f = re.sub(r"^(?:so nha|so)\s+", "", f)
            f = re.sub(r"^(?:kiet|hem|ngo|ngach|k|h)\s*\.?\s*[a-z]?\d+[a-z]?(?:[/\-][a-z0-9]+)*\s*", "", f)
            f = re.sub(r"^[a-z]?\d+[a-z]?(?:[/\-][a-z]?\d+[a-z]?)*\s+", "", f)
        f = re.sub(r"^(?:duong|pho)\s+", "", f)    # once: "Đường 2 Tháng 9" keeps its number
        f = re.sub(r"[^a-z0-9 ]", " ", f)
        f = re.sub(r"\s+", " ", f).strip()
        return f if re.search(r"[a-z]{2}", f) else None
    return None


def _h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:20]


def fingerprint(obs: ListingObs) -> str:
    """Stable identity key for a ListingObs (see module doc). Prices never enter it."""
    deal = "rent" if obs.kind == "rent" else "sale"
    area = round(obs.area_m2) if obs.area_m2 else None
    loc = None
    if obs.lat is not None and obs.lng is not None:
        loc = cell(obs.lat, obs.lng, GEO_CELL_M)
    else:
        street = obs.street or extract_street(obs.address)
        ward = obs.ward_code or match_ward(obs.ward_raw or obs.address)
        if street and ward:
            loc = f"s:{street}|w:{ward}"
    if loc and area:
        front = f"{round(obs.frontage_m, 1):.1f}" if obs.frontage_m else "na"
        return "fp:" + _h(f"{loc}|a:{area}|f:{front}|t:{obs.ptype}|d:{deal}")
    if obs.site_id:
        return f"site:{obs.site}:{obs.site_id}"
    if obs.url:
        return "url:" + _h(obs.url.split("#")[0].split("?")[0])
    return "raw:" + _h(f"{obs.site}|{fold(obs.title)}|{fold(obs.address)}|{area}|{obs.ptype}|{deal}")
