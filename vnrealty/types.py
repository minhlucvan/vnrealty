"""Shared value types passed between modules. Plain dataclasses; money in VND, area in m²."""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["ListingObs", "Comp", "Estimate", "Insufficient"]


@dataclass
class ListingObs:
    """One listing as read from one page at one moment. Site extractors return these; ingest stores them."""
    site: str
    seen_at: str                      # when the page was captured (ISO)
    kind: str = "asking"              # asking | rent | sale
    ptype: str = "other"              # land | house | apartment | shophouse | villa | chdv | room | other
    price: float | None = None        # VND (per month for rent); None = negotiable / not stated
    price_m2: float | None = None
    url: str | None = None
    site_id: str | None = None
    title: str | None = None
    address: str | None = None
    street: str | None = None
    ward_code: str | None = None
    ward_raw: str | None = None       # the ward/district text as printed, before mapping
    lat: float | None = None
    lng: float | None = None
    area_m2: float | None = None
    floor_area_m2: float | None = None
    frontage_m: float | None = None
    depth_m: float | None = None
    alley_m: float | None = None      # 0 = street frontage (mặt tiền); None = unknown
    floors: float | None = None
    bedrooms: float | None = None
    corner: bool | None = None
    direction: str | None = None
    legal: str | None = None          # so_hong | so_do | hdmb | giay_tay | unknown
    posted_at: str | None = None
    phone_hash: str | None = None     # sha1 of digits, never the number itself
    raw_ref: str | None = None        # path of the saved page text
    extra: dict = field(default_factory=dict)


@dataclass
class Comp:
    """A comparable used in a valuation, after selection and adjustment."""
    listing_id: int | None
    price: float
    area_m2: float
    price_m2: float
    adj_price_m2: float
    kind: str
    seen_at: str
    distance_km: float | None = None
    adjustments: dict = field(default_factory=dict)
    source: str | None = None


@dataclass
class Estimate:
    """A value with a band. Every valuation method returns one of these or an Insufficient."""
    method: str
    value: float
    lo: float
    hi: float
    n: int = 0
    as_of: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class Insufficient:
    """A method that could not produce a number says so — never a default value."""
    method: str
    reason: str
    detail: dict = field(default_factory=dict)
