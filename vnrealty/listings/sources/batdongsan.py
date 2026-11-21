"""batdongsan.com.vn — detail pages show a spec table (Mức giá, Diện tích, Mặt tiền, Đường vào, Hướng nhà, Pháp lý, Số tầng, Số phòng ngủ) and a footer (Ngày đăng, Mã tin); ids are the ``-pr<digits>`` URL suffix."""
from __future__ import annotations

from vnrealty.listings.sources import _common
from vnrealty.types import ListingObs

SITE = "batdongsan"
DOMAINS = ['batdongsan.com.vn']
LABELS: dict[str, list[str]] = {}


def parse(headers: dict, text: str) -> list[ListingObs]:
    """A text capture (headers + get_page_text output) → ListingObs list."""
    return _common.parse_text(SITE, headers, text, LABELS)


def from_capture(obj: dict) -> list[ListingObs]:
    """A JSON capture from browser/batdongsan.js → ListingObs list."""
    return _common.from_capture(obj, SITE if SITE != "generic" else None)
