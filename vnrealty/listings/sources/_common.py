"""Shared machinery for the site parsers: capture reading, the raw-fields → ListingObs normaliser, and generic
detail/search parsing of ``get_page_text`` output. Site modules only add label synonyms and URL conventions.

Raw fields (what the browser scripts emit and what text parsing recovers) are strings: ``price_text``,
``area_text``, ``ppm2_text``, ``dims_text``, ``frontage_text``, ``depth_text``, ``alley_text``, ``legal_text``,
``direction_text``, ``floors_text``, ``bedrooms_text``, ``floor_area_text``, ``ptype_text``, ``posted_text``, plus
``title``, ``address``, ``ward_raw``, ``url``, ``site_id``, ``lat``, ``lng``, ``description``, ``phone_hash``,
``deal`` and an optional ``labels`` dict (canonical label → raw value). All number parsing is ``listings.parse``.
"""
from __future__ import annotations

import re
from pathlib import Path

from vnrealty.listings import parse as P
from vnrealty.types import ListingObs

__all__ = ["read_text_capture", "normalize", "parse_text", "from_capture", "site_id_from_url", "metres"]

_ID_PATTERNS = {
    "batdongsan": r"-pr(\d{5,})",
    "chotot": r"/(\d{6,})\.htm",
    "alonhadat": r"-(\d{5,})\.html?",
    "muaban": r"-id(\d{5,})",
    "facebook": r"(?:posts|permalink)/(\d{6,})|story_fbid=(\d{6,})",
}


def site_id_from_url(url: str | None, site: str) -> str | None:
    """Listing id from a URL by the site's convention, else a trailing ≥5-digit number. Mirrors core.js."""
    if not url:
        return None
    u = url.split("#")[0]
    m = re.search(_ID_PATTERNS[site], u) if site in _ID_PATTERNS else None
    if not m:
        m = re.search(r"(\d{5,})(?:\.html?|\.htm)?/?$", u.split("?")[0])
    if not m:
        return None
    return next(g for g in m.groups() if g)


def read_text_capture(path: str | Path) -> tuple[dict, str]:
    """Split a text capture into (headers, page text). Headers are ``# key: value`` lines up to the first blank line."""
    raw = Path(path).read_text(encoding="utf-8")
    headers: dict[str, str] = {}
    lines = raw.splitlines()
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        k, _, v = lines[i][1:].partition(":")
        if k.strip():
            headers[k.strip().lower()] = v.strip()
        i += 1
    if i < len(lines) and not lines[i].strip():
        i += 1
    return headers, "\n".join(lines[i:])


def metres(s: str | None) -> float | None:
    """A length in metres from "5 m", "5,5m", "6". ``None`` when absent or implausible (> 200 m)."""
    f = P.fold(s)
    m = re.search(r"\d+(?:[.,]\d+)?", f)
    if not m:
        return None
    v = P.parse_number(m.group(0), "ty")
    return v if v is not None and 0 <= v <= 200 else None


def _labels_to_fields(labels: dict) -> dict:
    mapping = {"price": "price_text", "area": "area_text", "floor_area": "floor_area_text", "frontage": "frontage_text",
               "depth": "depth_text", "alley": "alley_text", "legal": "legal_text", "direction": "direction_text",
               "floors": "floors_text", "bedrooms": "bedrooms_text", "address": "address", "posted": "posted_text",
               "site_id": "site_id", "ptype": "ptype_text", "title": "title"}
    return {mapping[k]: v for k, v in (labels or {}).items() if k in mapping and v}


PTYPE_CODES = {"land", "house", "apartment", "shophouse", "villa", "chdv", "room", "homestay"}
LEGAL_CODES = {"so_hong", "so_do", "co_so", "so_chung", "cho_so", "hdmb", "giay_tay"}


def normalize(site: str, seen_at: str, fields: dict, deal: str | None = None, extra: dict | None = None) -> ListingObs:
    """Raw fields → ListingObs. Price per m² is multiplied out only when the area is known; a rent quoted per year is
    divided by 12 (``extra.price_per`` keeps what was printed). ``ward_code``/``street`` are left to ingest."""
    f = dict(_labels_to_fields(fields.get("labels") or {}))
    f.update({k: v for k, v in fields.items() if v not in (None, "") and k != "labels"})
    url = f.get("url")
    text_all = " ".join(str(f.get(k) or "") for k in ("title", "description"))
    deal = f.get("deal") or deal or P.detect_deal(f"{url or ''} {f.get('title') or ''}") or "sale"
    area = P.parse_area(f.get("area_text"))
    dims = P.parse_dims(f.get("dims_text")) or P.parse_dims(f.get("title"))
    if area is None and dims:
        area = round(dims[0] * dims[1], 2)
    pr = P.parse_price(f.get("price_text"), deal=deal)
    price, price_m2 = pr["value"], None
    if pr["per"] == "m2" and price is not None:
        price_m2, price = price, (price * area if area else None)
    elif pr["per"] == "year" and price is not None:
        price = price / 12.0
    if price is None and pr["value"] is None and not pr["negotiable"] and f.get("ppm2_text") and area:
        pm = P.parse_price(f.get("ppm2_text"), deal=deal)
        if pm["per"] == "m2" and pm["value"] is not None:
            price_m2, price = pm["value"], pm["value"] * area
    if price is not None and price_m2 is None and area:
        price_m2 = price / area
    ptype = f.get("ptype") if f.get("ptype") in PTYPE_CODES else "other"   # an extractor that already knows the type wins
    for src in (() if ptype != "other" else (f.get("ptype_text"), f.get("house_type"), f.get("land_type"), f.get("category_raw"),
                                              f.get("title"), (url or "").replace("-", " "), f.get("description"))):
        ptype = P.detect_ptype(src)
        if ptype != "other":
            break
    acc = P.parse_access(f"{text_all} {f.get('house_type') or ''}")   # "Nhà mặt phố" = street frontage
    alley = metres(f.get("alley_text")) if f.get("alley_text") else acc["alley_m"]
    frontage = metres(f.get("frontage_text")) if f.get("frontage_text") else (_num(f.get("frontage_m")) or (dims[0] if dims else None))
    depth = metres(f.get("depth_text")) if f.get("depth_text") else (_num(f.get("depth_m")) or (dims[1] if dims else None))
    if area is None:
        area = _num(f.get("area_m2"))
        if price is not None and area and price_m2 is None:
            price_m2 = price / area
    legal = f.get("legal") if f.get("legal") in LEGAL_CODES else P.detect_legal(f.get("legal_text") or f.get("legal"))
    if legal in ("unknown", "co_so"):   # the description may name the certificate type the label leaves out
        better = P.detect_legal(text_all)
        if better != "unknown" and not (legal == "co_so" and better == "co_so"):
            legal = better
    direction = P.detect_direction(f.get("direction_text")) or P.detect_direction(text_all)
    lat, lng = _num(f.get("lat")), _num(f.get("lng"))
    phone = f.get("phone_hash") or (P.find_phone_hashes(text_all) or [None])[0]
    x = {"price_text": f.get("price_text"), "price_per": pr["per"], "negotiable": pr["negotiable"], "deal": deal}
    if pr["lo"] is not None:
        x.update(price_lo=pr["lo"], price_hi=pr["hi"])
    if acc["car_access"]:
        x["car_access"] = True
    if phone:
        x["phone_hash"] = phone
    for k in ("project", "street", "district_raw", "land_type", "house_type", "apartment_type", "furnishing", "category_raw"):
        if f.get(k):
            x[k] = f[k]
    x.update(extra or {})
    return ListingObs(
        site=site, seen_at=seen_at, kind="rent" if deal == "rent" else "asking", ptype=ptype,
        price=price, price_m2=price_m2, url=url, site_id=str(f["site_id"]).strip() if f.get("site_id") else site_id_from_url(url, site),
        title=P.redact_phones(f.get("title")) if f.get("title") else None,
        address=f.get("address"), street=f.get("street"), ward_raw=f.get("ward_raw") or f.get("address"),
        lat=lat, lng=lng, area_m2=area, floor_area_m2=P.parse_area(f.get("floor_area_text")),
        frontage_m=frontage, depth_m=depth, alley_m=alley,
        floors=P.parse_int(f.get("floors_text")) if f.get("floors_text") else _num(f.get("floors")),
        bedrooms=P.parse_int(f.get("bedrooms_text")) if f.get("bedrooms_text") else _num(f.get("bedrooms")),
        corner=P.detect_corner(text_all), direction=direction, legal=legal,
        posted_at=P.parse_posted(f.get("posted_text"), seen_at), phone_hash=phone, extra=x)


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


_PRICE_LINE = re.compile(r"\d\s*(tỷ|tỉ|triệu|tr\b)|thỏa thuận|thoả thuận", re.I)


def _title_line(lines: list[str]) -> int | None:
    for i, l in enumerate(lines):
        fl = P.fold(l)
        if 15 <= len(l) <= 200 and re.search(r"\b(ban|cho thue|can ban|chuyen nhuong)\b", fl) and not fl.startswith(("mua ban", "nha dat ban", "cho thue nha dat")):
            return i
    return None


def parse_text(site: str, headers: dict, text: str, labels: dict | None = None) -> list[ListingObs]:
    """Parse ``get_page_text`` output. ``# kind: detail`` → one listing from the label table and the title line;
    ``# kind: search`` → one listing per price-anchored card (no per-card URL is available in page text)."""
    seen_at = headers.get("seen_at") or ""
    deal = headers.get("deal")
    kind = (headers.get("kind") or "detail").lower()
    lines = [l.strip() for l in (text or "").splitlines()]
    extra = {"search": headers["search"]} if headers.get("search") else {}
    if kind == "search":
        return [normalize(site, seen_at, c, deal, extra) for c in _cards(lines)]
    labs = P.parse_label_table(lines, labels)
    ti = _title_line(lines)
    window = "\n".join(lines[ti:ti + 60]) if ti is not None else ""
    fields = {"labels": labs, "url": headers.get("url"), "title": lines[ti] if ti is not None else headers.get("title"),
              "description": window[:3000]}
    if "address" not in labs and ti is not None:
        addr = next((l for l in lines[ti + 1:ti + 6] if 10 <= len(l) <= 200 and not _PRICE_LINE.search(l)
                     and re.search(r"đà nẵng|da nang|quảng nam|phường|quận|xã |huyện", l, re.I)), None)
        if addr:
            fields["address"] = addr
    if "price" not in labs or "area" not in labs:
        fields.update({k: v for k, v in P.card_fields(window).items() if k not in fields})
    return [normalize(site, seen_at, fields, deal, extra)]


def _cards(lines: list[str]) -> list[dict]:
    anchors = [i for i, l in enumerate(lines) if l and len(l) <= 120 and _PRICE_LINE.search(l)]
    titles: list[int] = []
    for a in anchors:
        t = next((j for j in range(a, max(-1, a - 4), -1) if len(lines[j]) >= 20 and not _PRICE_LINE.search(lines[j][:25])), None)
        if t is None and len(lines[a]) >= 30:
            t = a
        if t is not None and (not titles or t > titles[-1]):
            titles.append(t)
    cards = []
    for k, t in enumerate(titles):
        end = titles[k + 1] if k + 1 < len(titles) else min(len(lines), t + 12)
        block = "\n".join(lines[t:end])
        f = P.card_fields(block)
        if "price_text" not in f and "area_text" not in f:
            continue
        loc = next((l for l in lines[t + 1:end] if re.search(r",\s*(đà nẵng|da nang|quảng nam)", l, re.I)), None)
        cards.append(dict(f, title=lines[t], address=loc, ward_raw=loc, description=block[:1500]))
    return cards


_SRP_KEYS = {"prid": "site_id", "category": "ptype_text", "ppm_text": "ppm2_text", "location": "address",
             "published": "posted_text", "bedrooms": "bedrooms_text"}


def _srp_item(columns: list[str], row) -> dict:
    """One compact 'srp' row (batdongsan.js: ``columns`` + arrays) → a raw-fields dict. The category slug
    ("ban-nha-rieng", "cho-thue-can-ho-chung-cu") gives ptype and deal."""
    if isinstance(row, dict):
        d = dict(row)
    else:
        d = dict(zip(columns, row))
    out = {_SRP_KEYS.get(k, k): v for k, v in d.items() if v not in (None, "")}
    if out.get("address"):
        out["ward_raw"] = out["address"]
    cat = str(d.get("category") or "")
    if cat:
        out["ptype_text"] = cat.replace("-", " ")
        out.setdefault("deal", "rent" if cat.startswith("cho-thue") else ("sale" if cat.startswith("ban") else None))
    out.pop("vip", None)
    return out


def from_capture(obj: dict, site: str | None = None) -> list[ListingObs]:
    """Items of a browser-script JSON capture → ListingObs (kind detail|search, or batdongsan's compact 'srp'
    rows). Other kinds (map, zoning) yield ``[]``."""
    site = site or obj.get("site") or "generic"
    if obj.get("kind") == "srp":
        obj = dict(obj, kind="search", items=[_srp_item(obj.get("columns") or [], r) for r in obj.get("items") or []])
    if obj.get("kind") not in ("detail", "search"):
        return []
    seen_at = obj.get("seen_at") or ""
    deal = obj.get("deal")
    extra = {"search": obj["search"]} if obj.get("search") else {}
    out = []
    for it in obj.get("items") or []:
        if not isinstance(it, dict):
            continue
        it = dict(it)
        it.setdefault("url", obj.get("url") if obj.get("kind") == "detail" else None)
        if it.get("card_text") and not it.get("description"):
            it["description"] = it["card_text"]
        o = normalize(site, seen_at, it, deal, extra)
        if o.price is None and o.area_m2 is None and not o.extra.get("negotiable"):
            continue          # a card with neither price nor area is not a listing observation
        out.append(o)
    return out
