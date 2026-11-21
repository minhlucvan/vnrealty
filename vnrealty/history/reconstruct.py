"""Reconstruct a property's yearly value history from a few anchors and a market index.

Only anchors are observed (a purchase price, a notarised sale, an appraisal); every other year is *reconstructed*
and labelled so, with a band that widens with distance to the nearest anchor.

Method: each anchor a gives a ratio rₐ = valueₐ / I(tₐ) (the property's price in index units). Between two anchors
the ratio is interpolated log-linearly in time, outside them it is held at the nearest anchor's, and
value(t) = r(t) · I(t). The path therefore passes exactly through every anchor, and between anchors it moves with
the market while drifting from one anchor's relative level to the next.

Band (fraction of value): base(nearest anchor) + ``band_per_year`` × years to it, where base is ``fact_band`` for
'fact' anchors and ``estimate_band`` for 'estimate' anchors; minimised over anchors, capped at ``max_band``.
lo = v·(1 − band), hi = v·(1 + band).

Units: VND (or whatever the anchors are in); index levels any positive unit; months ``YYYY-MM``; years int.
A year the index does not cover yields ``value: None, label: 'insufficient'`` with a reason — never a guess.
"""
from __future__ import annotations

import math

from vnrealty.types import Insufficient

__all__ = ["reconstruct", "index_at"]


def _t(month: str) -> float:
    """Decimal time of the middle of month ``YYYY-MM``."""
    return int(month[:4]) + (int(month[5:7]) - 0.5) / 12


def index_at(index_series: list[tuple[str, float]], t: float) -> float | None:
    """Index level at decimal time ``t`` by linear interpolation between month midpoints; None outside coverage."""
    pts = sorted((_t(m), float(v)) for m, v in index_series if v is not None and v > 0)
    if not pts or t < pts[0][0] - 1e-9 or t > pts[-1][0] + 1e-9:
        return None
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0) if t1 > t0 else v1
    return pts[-1][1]


def reconstruct(anchors: list[tuple[str, float, str]], index_series: list[tuple[str, float]], years: list[int],
                band_per_year: float = 0.05, fact_band: float = 0.0, estimate_band: float = 0.10,
                max_band: float = 0.9) -> list[dict] | Insufficient:
    """Yearly ``{year, value, lo, hi, label, years_to_anchor, note}`` for each year in ``years``.

    ``anchors``: ``(YYYY-MM, value, 'fact'|'estimate')``. A year containing a fact anchor reports that fact exactly
    (label 'fact', the latest fact in the year); other years are evaluated mid-year (label 'reconstructed').
    ``Insufficient`` when there are no anchors or the index covers no anchor month.
    """
    if not anchors:
        return Insufficient("reconstruct", "no anchors")
    pts = []
    skipped = []
    for m, v, kind in anchors:
        if kind not in ("fact", "estimate"):
            raise ValueError(f"anchor kind must be 'fact' or 'estimate', got {kind!r}")
        lvl = index_at(index_series, _t(m))
        if lvl is None or v is None or v <= 0:
            skipped.append(m)
            continue
        pts.append((_t(m), math.log(v / lvl), kind, m, float(v)))
    if not pts:
        return Insufficient("reconstruct", "index does not cover any anchor month", {"skipped": skipped})
    pts.sort()

    def log_ratio(t: float) -> float:
        if t <= pts[0][0]:
            return pts[0][1]
        if t >= pts[-1][0]:
            return pts[-1][1]
        for a, b in zip(pts, pts[1:]):
            if a[0] <= t <= b[0]:
                w = (t - a[0]) / (b[0] - a[0]) if b[0] > a[0] else 1.0
                return a[1] * (1 - w) + b[1] * w
        return pts[-1][1]

    def band(t: float) -> tuple[float, float]:
        best = min(((fact_band if k == "fact" else estimate_band) + band_per_year * abs(t - ta), abs(t - ta))
                   for ta, _, k, _, _ in pts)
        return min(max_band, best[0]), best[1]

    out = []
    for y in years:
        facts = [p for p in pts if p[2] == "fact" and p[3][:4] == str(y)]
        if facts:
            f = facts[-1]
            out.append({"year": y, "value": f[4], "lo": f[4] * (1 - fact_band), "hi": f[4] * (1 + fact_band),
                        "label": "fact", "years_to_anchor": 0.0, "note": f"fact anchor {f[3]}"})
            continue
        t = y + 0.5
        lvl = index_at(index_series, t)
        if lvl is None:
            out.append({"year": y, "value": None, "lo": None, "hi": None, "label": "insufficient",
                        "years_to_anchor": None, "note": "index does not cover this year"})
            continue
        v = math.exp(log_ratio(t)) * lvl
        b, dist = band(t)
        out.append({"year": y, "value": v, "lo": v * (1 - b), "hi": v * (1 + b), "label": "reconstructed",
                    "years_to_anchor": dist, "note": f"index-moved; band ±{b:.0%}"})
    return out
