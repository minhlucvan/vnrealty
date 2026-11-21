"""Value a property by moving a known past price with a market index.

value = purchase_price × I(as_of) / I(purchase_month). The index series is passed in (``market/index.py`` builds
it); this module never fetches one. Point in time: the as-of level is the latest index month ``<= as_of``'s month.

Band: ±z₉₀ · σ_m · √months (lognormal), where σ_m is the standard deviation of monthly log changes of the index
over the holding window — the further the move, the wider the band — floored at ``min_band``. That band covers index
noise only; it cannot know whether the purchase was itself a fair price (say so in reports).

Units: VND; index levels are any positive unit (typically asking VND/m²); months ``YYYY-MM``.
"""
from __future__ import annotations

import math

from vnrealty.types import Estimate, Insufficient

__all__ = ["value_by_index", "level_at"]

Z90 = 1.2815515655446004


def level_at(index_series: list[tuple[str, float]], month: str) -> tuple[str, float] | None:
    """The latest (month, level) with month ``<= month`` (``YYYY-MM``), or None."""
    pts = sorted((m[:7], float(v)) for m, v in index_series if v is not None and v > 0 and m[:7] <= month[:7])
    return pts[-1] if pts else None


def value_by_index(purchase_price: float, purchase_month: str, index_series: list[tuple[str, float]], as_of: str,
                   min_band: float = 0.05, max_lag_months: int = 6) -> Estimate | Insufficient:
    """Purchase price (VND) moved by the index from ``purchase_month`` to ``as_of`` → Estimate with a band.

    ``Insufficient`` when the index has no level for the purchase month itself, none at or before ``as_of``, or its
    latest level lags ``as_of`` by more than ``max_lag_months``.
    """
    m = "index_moved"
    if not purchase_price or purchase_price <= 0:
        return Insufficient(m, "purchase price must be positive")
    series = {k[:7]: float(v) for k, v in index_series if v is not None and v > 0}
    pm = purchase_month[:7]
    if pm not in series:
        return Insufficient(m, f"index has no level for the purchase month {pm}")
    now = level_at(index_series, as_of[:7])
    if now is None or now[0] < pm:
        return Insufficient(m, f"index has no level between {pm} and {as_of[:7]}")
    ay, am = int(as_of[:4]), int(as_of[5:7])
    ny, nm = int(now[0][:4]), int(now[0][5:7])
    lag = (ay - ny) * 12 + (am - nm)
    if lag > max_lag_months:
        return Insufficient(m, f"latest index level {now[0]} lags {as_of[:7]} by {lag} months (> {max_lag_months})")
    ratio = now[1] / series[pm]
    window = sorted((k, v) for k, v in series.items() if pm <= k <= now[0])
    rets = [math.log(b[1] / a[1]) for a, b in zip(window, window[1:])]
    py, pmo = int(pm[:4]), int(pm[5:7])
    months = (ny - py) * 12 + (nm - pmo)
    if len(rets) >= 2:
        mu = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))
    else:
        sd = 0.0
    half = max(min_band, Z90 * sd * math.sqrt(max(months, 1)))
    v = purchase_price * ratio
    return Estimate(m, v, v * math.exp(-half), v * math.exp(half), n=len(window), as_of=as_of,
                    detail={"ratio": ratio, "from": [pm, series[pm]], "to": list(now), "lag_months": lag,
                            "months_held": months, "monthly_log_sd": sd, "half_band_log": half,
                            "caveat": "band covers index noise only, not whether the purchase price was fair"})
