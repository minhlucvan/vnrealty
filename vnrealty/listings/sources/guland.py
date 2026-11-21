"""guland.vn listings (the planning map is browser/zoning.js). Markup unverified; generic labels plus lane/road synonyms."""
from __future__ import annotations

from vnrealty.listings.sources import _common
from vnrealty.types import ListingObs

SITE = "guland"
DOMAINS = ['guland.vn']
LABELS: dict[str, list[str]] = {'alley': ['Đường trước', 'Lộ giới'], 'ptype': ['Loại BĐS', 'Loại']}


def parse(headers: dict, text: str) -> list[ListingObs]:
    """A text capture (headers + get_page_text output) → ListingObs list."""
    return _common.parse_text(SITE, headers, text, LABELS)


def from_capture(obj: dict) -> list[ListingObs]:
    """A JSON capture from browser/guland.js → ListingObs list."""
    return _common.from_capture(obj, SITE if SITE != "generic" else None)
