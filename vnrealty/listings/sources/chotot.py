"""nhatot.com / chotot.com — labelled params (Diện tích đất, Chiều ngang, Chiều dài, Giấy tờ pháp lý, Tổng số tầng); ids are ``/<digits>.htm``."""
from __future__ import annotations

from vnrealty.listings.sources import _common
from vnrealty.types import ListingObs

SITE = "chotot"
DOMAINS = ['nhatot.com', 'chotot.com']
LABELS: dict[str, list[str]] = {'area': ['Diện tích đất'], 'frontage': ['Chiều ngang'], 'depth': ['Chiều dài'], 'legal': ['Giấy tờ pháp lý'], 'floors': ['Tổng số tầng'], 'ptype': ['Loại hình nhà ở', 'Loại hình đất', 'Loại hình căn hộ'], 'direction': ['Hướng cửa chính']}


def parse(headers: dict, text: str) -> list[ListingObs]:
    """A text capture (headers + get_page_text output) → ListingObs list."""
    return _common.parse_text(SITE, headers, text, LABELS)


def from_capture(obj: dict) -> list[ListingObs]:
    """A JSON capture from browser/chotot.js → ListingObs list."""
    return _common.from_capture(obj, SITE if SITE != "generic" else None)


ROW_COLUMNS = ["id", "type", "category", "price_vnd", "size_m2", "price_million_per_m2", "lat", "lng", "area_name",
               "ward_name", "street_name", "land_type", "house_type", "apartment_type", "legal", "rooms", "floors",
               "width_m", "length_m", "main_street", "project_name", "orig_list_time_ms"]


def from_rows(text: str) -> list[ListingObs]:
    """The compact capture from browser/nhatot.js: a ``#total=<n>|url=<href>|seen_at=<iso>`` header line, then one
    ``|``-separated row per ad (``ROW_COLUMNS``). Typed site values become raw strings for the one parser;
    ``main_street`` true means street frontage (alley 0)."""
    import datetime as _dt

    lines = [l for l in (text or "").splitlines() if l.strip()]
    if not lines or not lines[0].startswith("#total="):
        return []
    head = dict(kv.split("=", 1) for kv in lines[0][1:].split("|") if "=" in kv)
    seen_at = head.get("seen_at") or ""
    out = []
    for line in lines[1:]:
        d = dict(zip(ROW_COLUMNS, line.split("|")))
        if not d.get("id"):
            continue
        deal = "rent" if d.get("type") == "u" else "sale"
        f = {"site_id": d["id"], "url": f"https://www.nhatot.com/{d['id']}.htm", "deal": deal,
             "price_text": f"{d['price_vnd']} đ" if d.get("price_vnd") else None,
             "area_text": f"{d['size_m2']} m2" if d.get("size_m2") else None,
             "lat": d.get("lat"), "lng": d.get("lng"),
             "address": ", ".join(x for x in (d.get("street_name"), d.get("ward_name"), d.get("area_name")) if x) or None,
             "ward_raw": ", ".join(x for x in (d.get("ward_name"), d.get("area_name")) if x) or None,
             "ptype_text": " ".join(x for x in (d.get("category"), d.get("house_type"), d.get("land_type"),
                                                d.get("apartment_type")) if x) or None,
             "legal_text": d.get("legal"), "bedrooms_text": d.get("rooms"), "floors_text": d.get("floors"),
             "frontage_text": d.get("width_m"), "depth_text": d.get("length_m"),
             "title": d.get("project_name") or None}
        if (d.get("main_street") or "").lower() in ("true", "1"):
            f["alley_text"] = "0"
        ms = d.get("orig_list_time_ms")
        if ms and ms.isdigit():
            f["posted_text"] = _dt.datetime.fromtimestamp(int(ms) / 1000, _dt.timezone.utc).date().isoformat()
        out.append(_common.normalize(SITE, seen_at, f, deal))
    return out
