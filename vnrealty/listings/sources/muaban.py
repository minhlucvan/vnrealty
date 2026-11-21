"""muaban.net real estate — generic labels; ids are ``-id<digits>``."""
from __future__ import annotations

from vnrealty.listings.sources import _common
from vnrealty.types import ListingObs

SITE = "muaban"
DOMAINS = ['muaban.net']
LABELS: dict[str, list[str]] = {}


def parse(headers: dict, text: str) -> list[ListingObs]:
    """A text capture (headers + get_page_text output) → ListingObs list."""
    return _common.parse_text(SITE, headers, text, LABELS)


def from_capture(obj: dict) -> list[ListingObs]:
    """A JSON capture from browser/muaban.js → ListingObs list."""
    return _common.from_capture(obj, SITE if SITE != "generic" else None)
