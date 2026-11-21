"""Social posts (Facebook groups/pages, Zalo-web-like feeds) → ListingObs via ``parse.parse_post``.

Only posts that read like a listing (``confidence >= MIN_CONFIDENCE``) become observations; the rest are dropped.
Names and profile links never enter (browser/social.js does not collect them); phones are hashed.
"""
from __future__ import annotations

import re

from vnrealty.listings import parse as P
from vnrealty.listings.sources._common import site_id_from_url
from vnrealty.types import ListingObs

SITE = "facebook"
DOMAINS = ["facebook.com", "fb.com", "zalo.me", "chat.zalo.me"]
MIN_CONFIDENCE = 0.55


def _obs(site: str, seen_at: str, text: str, permalink: str | None, time_text: str | None, extra: dict) -> ListingObs | None:
    d = P.parse_post(text)
    if d["confidence"] < MIN_CONFIDENCE:
        return None
    x = {"price_per": d["price_per"], "negotiable": d["negotiable"], "deal": d["deal"], "confidence": d["confidence"],
         "source": "social"}
    if d["price_lo"] is not None:
        x.update(price_lo=d["price_lo"], price_hi=d["price_hi"])
    if d["phone_hash"]:
        x["phone_hash"] = d["phone_hash"]
    if d["car_access"]:
        x["car_access"] = True
    x.update(extra)
    price_m2 = d["price_m2"] or (d["price"] / d["area_m2"] if d["price"] is not None and d["area_m2"] else None)
    return ListingObs(site=site, seen_at=seen_at, kind=d["kind"], ptype=d["ptype"], price=d["price"], price_m2=price_m2,
                      url=permalink, site_id=site_id_from_url(permalink, "facebook") if permalink else None,
                      title=d["title"], ward_code=d["ward_code"], ward_raw=None, area_m2=d["area_m2"],
                      frontage_m=d["frontage_m"], depth_m=d["depth_m"], alley_m=d["alley_m"], corner=d["corner"],
                      direction=d["direction"], legal=d["legal"], posted_at=P.parse_posted(time_text, seen_at),
                      phone_hash=d["phone_hash"], extra=x)


def from_capture(obj: dict) -> list[ListingObs]:
    """A JSON capture from browser/social.js (``kind: social``) → listing-like posts as ListingObs."""
    if obj.get("kind") != "social":
        return []
    site = obj.get("site") or SITE
    extra = {"search": obj["search"]} if obj.get("search") else {}
    out = []
    for it in obj.get("items") or []:
        o = _obs(site, obj.get("seen_at") or "", it.get("text") or "", it.get("permalink"), it.get("time_text"), extra)
        if o:
            out.append(o)
    return out


def parse(headers: dict, text: str) -> list[ListingObs]:
    """A text capture of a feed: posts are blocks separated by blank lines; listing-like blocks become ListingObs."""
    site = headers.get("site") or SITE
    extra = {"search": headers["search"]} if headers.get("search") else {}
    out = []
    for block in re.split(r"\n\s*\n", text or ""):
        o = _obs(site, headers.get("seen_at") or "", block.strip(), None, None, extra)
        if o:
            out.append(o)
    return out
