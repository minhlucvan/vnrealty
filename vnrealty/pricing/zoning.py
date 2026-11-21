"""Pricing parameters and the two zoning rules that turn a lot into buildable floor area.

* :func:`load_params` reads ``reference/pricing_params.json`` (every entry has value, unit, basis, sources).
* :func:`buildable_ratio` — maximum footprint / lot area for an individual house, interpolated on the QCVN
  01:2021/BXD table (sourced).
* :func:`floors_allowed` — maximum floors from the access width under Đà Nẵng QĐ 07/2026/QĐ-UBND (press-reported,
  sourced): kiệt bands by width; street frontage by carriageway width, or the rule's lowest street band as an
  explicit *lower bound* when the carriageway is unknown.
* :func:`gfa` — gross floor area = lot area × buildable ratio × floors (m²).

Units: area m², widths m, ratios fractions. Missing inputs give :class:`~vnrealty.types.Insufficient`.
"""
from __future__ import annotations

import json
from pathlib import Path

from vnrealty.store.db import REPO
from vnrealty.types import Insufficient

__all__ = ["PARAMS_PATH", "load_params", "pv", "buildable_ratio", "floors_allowed", "gfa"]

PARAMS_PATH = REPO / "reference" / "pricing_params.json"
_CACHE: dict[str, dict] = {}


def load_params(path: str | Path | None = None) -> dict:
    """The ``params`` block of ``reference/pricing_params.json`` (or ``path``); cached per path."""
    key = str(path or PARAMS_PATH)
    if key not in _CACHE:
        with open(key, encoding="utf-8") as fh:
            _CACHE[key] = json.load(fh)["params"]
    return _CACHE[key]


def pv(params: dict, name: str, key: str = "value"):
    """One parameter value: ``params[name][key]`` (KeyError when absent — parameters are never defaulted)."""
    return params[name][key]


def buildable_ratio(area_m2: float | None, params: dict | None = None) -> float | Insufficient:
    """Maximum net building density (footprint ÷ lot area, fraction) for a lot of ``area_m2`` m².

    Linear between the QCVN 01:2021/BXD points (90 m² → 1.0, 100 → 0.9, 200 → 0.7, 300 → 0.6, 500 → 0.5,
    1000 → 0.4), flat outside. The code's ≤100 m² / ≤25 m 100% exception is not applied (conservative).
    """
    if not area_m2 or area_m2 <= 0:
        return Insufficient("buildable_ratio", "lot area unknown")
    pts = sorted((params or load_params())["buildable_ratio_by_lot"]["points"])
    if area_m2 <= pts[0][0]:
        return float(pts[0][1])
    if area_m2 >= pts[-1][0]:
        return float(pts[-1][1])
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= area_m2 <= x1:
            return y0 + (y1 - y0) * (area_m2 - x0) / (x1 - x0)
    return float(pts[-1][1])  # pragma: no cover


def floors_allowed(alley_m: float | None, road_width_m: float | None = None,
                   params: dict | None = None) -> dict | Insufficient:
    """Maximum floors for a lot reached by a kiệt of ``alley_m`` m (0 = street frontage).

    Returns ``{"floors", "max_height_m" (None when not stated), "bound": "rule" | "lower", "basis"}``.
    Street frontage uses ``road_width_m`` (existing carriageway, m) when known; unknown → the lowest street band as a
    lower bound (``bound='lower'``). A carriageway ≥ 10.5 m is set by the zoning plan → Insufficient. Unknown alley
    width → Insufficient.
    """
    p = params or load_params()
    if alley_m is None:
        return Insufficient("floors_allowed", "alley width unknown (alley_m is None)")
    if alley_m > 0:
        for lo, hi, floors, height in p["floors_by_alley"]["bands"]:
            if alley_m >= lo and (hi is None or alley_m < hi):
                return {"floors": int(floors), "max_height_m": height, "bound": "rule",
                        "basis": f"kiệt {alley_m:g} m → band [{lo}, {hi if hi is not None else '∞'}) m: {floors} floors"
                                 f" / {height} m (QĐ 07/2026; current width used as lộ giới proxy)"}
        return Insufficient("floors_allowed", f"no band for alley {alley_m} m")  # pragma: no cover
    st = p["floors_by_street"]
    if road_width_m is None:
        f = int(st["street_unknown_floors"])
        return {"floors": f, "max_height_m": None, "bound": "lower",
                "basis": f"street frontage, carriageway unknown: lowest street band ({f} floors) as a lower bound"}
    for lo, hi, floors in st["bands"]:
        if lo <= road_width_m < hi:
            return {"floors": int(floors), "max_height_m": None, "bound": "rule",
                    "basis": f"street carriageway {road_width_m:g} m → {floors} floors (QĐ 07/2026)"}
    return Insufficient("floors_allowed", f"carriageway {road_width_m} m ≥ 10.5 m: height set by the zoning plan")


def gfa(area_m2: float | None, alley_m: float | None, road_width_m: float | None = None,
        params: dict | None = None) -> dict | Insufficient:
    """Gross floor area (m²) of the largest simple build: area × buildable ratio × floors allowed.

    Returns ``{"gfa_m2", "footprint_m2", "buildable_ratio", "floors", "bound", "basis"}`` or Insufficient.
    """
    p = params or load_params()
    br = buildable_ratio(area_m2, p)
    if isinstance(br, Insufficient):
        return br
    fl = floors_allowed(alley_m, road_width_m, p)
    if isinstance(fl, Insufficient):
        return fl
    fp = area_m2 * br
    return {"gfa_m2": fp * fl["floors"], "footprint_m2": fp, "buildable_ratio": br, "floors": fl["floors"],
            "bound": fl["bound"], "basis": f"{area_m2:g} m² × {br:.2f} (QCVN 01:2021) × {fl['floors']} floors; "
                                            + fl["basis"]}
