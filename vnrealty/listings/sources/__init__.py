"""Site parsers. Each module exposes ``SITE``, ``DOMAINS``, ``parse(headers, text)`` for text captures and
``from_capture(obj)`` for browser-script JSON captures; both return ``list[ListingObs]``.

``detect_site(url)`` maps a URL to a module name (``generic`` when unknown); ``parse``/``from_capture`` here dispatch.
"""
from __future__ import annotations

from urllib.parse import urlparse

from vnrealty.listings.sources import alonhadat, batdongsan, bds68, chotot, generic, guland, muaban, social
from vnrealty.types import ListingObs

__all__ = ["SITES", "detect_site", "parse", "from_capture"]

SITES = {m.SITE if m is not social else "social": m
         for m in (batdongsan, chotot, alonhadat, guland, muaban, bds68, social, generic)}
_ALIASES = {"nhatot": "chotot", "facebook": "social", "zalo": "social", "guland_map": "guland"}


def detect_site(url: str | None) -> str:
    """Module name for a URL by its host, ``generic`` when no parser claims it."""
    host = (urlparse(url or "").hostname or "").lower()
    for name, mod in SITES.items():
        if any(host == d or host.endswith("." + d) for d in mod.DOMAINS):
            return name
    return "generic"


def _module(site: str | None, url: str | None):
    s = _ALIASES.get(site or "", site or "")
    if s in SITES:
        return SITES[s]
    return SITES[detect_site(url)]


def parse(headers: dict, text: str) -> list[ListingObs]:
    """Dispatch a text capture by its ``site`` header (or URL host)."""
    if (headers.get("kind") or "").lower() == "social":
        return social.parse(headers, text)
    mod = _module(headers.get("site"), headers.get("url"))
    if mod is generic and headers.get("site"):
        from vnrealty.listings.sources import _common
        return _common.parse_text(headers["site"], headers, text, generic.LABELS)
    return mod.parse(headers, text)


def from_capture(obj: dict) -> list[ListingObs]:
    """Dispatch a JSON capture by ``site`` (or URL host). Social captures go to the post parser."""
    if obj.get("kind") == "social":
        return social.from_capture(obj)
    mod = _module(obj.get("site"), obj.get("url"))
    if mod is generic:
        from vnrealty.listings.sources import _common
        return _common.from_capture(obj, obj.get("site") or "generic")
    return mod.from_capture(obj)
