"""alonhadat.com.vn — table rows (Mã tin, Hướng, Đường trước nhà = lane width in front, Pháp lý, Số lầu, Chiều ngang, Chiều dài, Loại BĐS); ids are ``-<digits>.html``."""
from __future__ import annotations

from vnrealty.listings.sources import _common
from vnrealty.types import ListingObs

SITE = "alonhadat"
DOMAINS = ['alonhadat.com.vn']
LABELS: dict[str, list[str]] = {'alley': ['Đường trước nhà'], 'floors': ['Số lầu'], 'ptype': ['Loại BĐS']}


def parse(headers: dict, text: str) -> list[ListingObs]:
    """A text capture (headers + get_page_text output) → ListingObs list."""
    return _common.parse_text(SITE, headers, text, LABELS)


def from_capture(obj: dict) -> list[ListingObs]:
    """A JSON capture from browser/alonhadat.js → ListingObs list."""
    return _common.from_capture(obj, SITE if SITE != "generic" else None)
