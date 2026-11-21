"""Đà Nẵng official land price table (bảng giá đất) lookup.

The state table is a **floor and the tax basis** (registration fee, land-use fees, compensation), **not market value**.
Use it as a sanity floor and for transaction-cost arithmetic, never as an estimate of what a lot will sell for.

Data: ``reference/official_land_prices_da_nang.json`` — only rows that could be sourced (resolution number + URL).
Units: VND per m².
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from vnrealty.store.db import REPO
from vnrealty.types import Insufficient

__all__ = ["load_table", "lookup", "fold"]

TABLE_PATH = REPO / "reference" / "official_land_prices_da_nang.json"


def fold(s: str) -> str:
    """NFC-normalise, strip diacritics (đ→d), lower-case, collapse spaces — for matching street names."""
    s = unicodedata.normalize("NFD", unicodedata.normalize("NFC", s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").replace("đ", "d").replace("Đ", "D")
    return " ".join(s.lower().split())


def load_table(path: str | Path | None = None) -> dict:
    """The whole reference document (decision, sources, rows)."""
    with open(path or TABLE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def lookup(street: str, position: int = 1, segment: str | None = None, area: str | None = None,
           path: str | Path | None = None) -> float | Insufficient:
    """Official price (VND/m²) for residential land on ``street`` at ``position`` (1 = street frontage).

    ``segment`` / ``area`` (substring, diacritics-insensitive) disambiguate streets with several rows. Returns
    ``Insufficient`` when the street/position is not in the sourced rows or the match is ambiguous.
    """
    doc = load_table(path)
    m = "official"
    rows = [r for r in doc["rows"] if fold(r["street"]) == fold(street)]
    if not rows:
        return Insufficient(m, f"street {street!r} not among the sourced rows of {doc['decision']['number']}")
    rows = [r for r in rows if r["position"] == position]
    if not rows:
        return Insufficient(m, f"position {position} not sourced for {street!r} (only VT1 rows were readable)")
    if segment:
        rows = [r for r in rows if fold(segment) in fold(r["segment"])]
    if area:
        rows = [r for r in rows if fold(area) in fold(r["area"])]
    if len(rows) != 1:
        return Insufficient(m, f"{len(rows)} rows match {street!r}; pass segment/area",
                            {"segments": [f"{r['segment']} ({r['area']})" for r in rows]})
    return float(rows[0]["price_m2"])
