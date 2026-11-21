"""Scenario price paths from the market's own drift plus nearby catalysts (projects that may or may not land).

Each catalyst has a chance ``p`` (0–1), an ``uplift`` (fraction added to the price once complete) and a completion
``year``; the market prices it in linearly from ``start_year`` until that year. Optional ``distance_km`` and
``decay_km`` shrink the uplift by exp(−distance/decay) — a project 3 km away moves a lot less than one next door.

* bear = market drift only (no catalyst lands);
* base = every catalyst at its chance (multiplier 1 + u·p·ramp);
* bull = every catalyst lands.

Paths are multipliers on today's price (1.0 at ``start_year``). ``hold_vs_sell`` turns a path into take-home cash
per year versus selling now and keeping the money on deposit. Rates are fractions; money VND.
"""
from __future__ import annotations

import math

__all__ = ["effective_uplift", "ramp", "market_path", "paths", "hold_vs_sell"]


def effective_uplift(c: dict) -> float:
    """Uplift (fraction) after distance decay exp(−distance_km / decay_km); unchanged when either is absent."""
    u = float(c["uplift"])
    d, k = c.get("distance_km"), c.get("decay_km")
    if d is not None and k:
        u *= math.exp(-float(d) / float(k))
    return u


def ramp(c: dict, t: int, start_year: int) -> float:
    """Share of the catalyst priced in after ``t`` years: t / max(1, year − start_year), clamped to [0, 1]."""
    return max(0.0, min(1.0, t / max(1, int(c["year"]) - start_year)))


def market_path(market: dict, years: int) -> list[float]:
    """Market-only multiplier path of length ``years`` + 1. ``market``: ``{'y1': first-year rate, 'later': rate}``."""
    out = [1.0]
    for t in range(1, years + 1):
        out.append(out[-1] * (1 + float(market["y1"] if t == 1 else market["later"])))
    return out


def _check(cats: list[dict]) -> None:
    for c in cats:
        if not 0 <= float(c["p"]) <= 1:
            raise ValueError(f"catalyst {c.get('id')}: p must be a fraction in [0, 1], got {c['p']}")


def paths(market: dict, catalysts: list[dict], years: int, start_year: int) -> dict:
    """Bear / base / bull multiplier paths and each catalyst's contribution at the horizon.

    ``contrib[id]`` = market(Y) × effective uplift × p × ramp(Y) — the expected lift (as a multiple of today's price)
    the catalyst adds at the horizon, before interaction with the others.
    """
    _check(catalysts)
    mkt = market_path(market, years)

    def path(w) -> list[float]:
        return [m * math.prod(1 + effective_uplift(c) * w(c) * ramp(c, t, start_year) for c in catalysts)
                for t, m in enumerate(mkt)]

    return {"years": [start_year + t for t in range(years + 1)], "bear": mkt, "base": path(lambda c: float(c["p"])),
            "bull": path(lambda c: 1.0),
            "contrib": {c.get("id", str(i)): mkt[years] * effective_uplift(c) * float(c["p"]) * ramp(c, years, start_year)
                        for i, c in enumerate(catalysts)},
            "effective_uplift": {c.get("id", str(i)): effective_uplift(c) for i, c in enumerate(catalysts)}}


def hold_vs_sell(price: float, share: float, sell_cost: float, deposit_rate: float, path: list[float],
                 holding_cost: float = 0.0, start_year: int | None = None) -> dict:
    """Per-year take-home from selling in year t on ``path`` versus selling now and earning ``deposit_rate``.

    take_home(t) = price × path[t] × share × (1 − sell_cost) − holding_cost × share × t (VND; holding_cost is VND per
    year for the whole property, e.g. tax and upkeep of an empty lot). deposit(t) = take_home(0) × (1 + r)^t.
    ``best`` is the year index with the largest edge (0 = sell now).
    """
    now = price * path[0] * share * (1 - sell_cost)
    rows = []
    for t, g in enumerate(path):
        th = price * g * share * (1 - sell_cost) - holding_cost * share * t
        dep = now * (1 + deposit_rate) ** t
        rows.append({"t": t, "year": (start_year + t) if start_year is not None else None, "price": price * g,
                     "take_home": th, "deposit": dep, "edge": th - dep,
                     "breakeven_price": price * path[0] * (1 + deposit_rate) ** t})
    best = max(range(len(rows)), key=lambda i: rows[i]["edge"]) if rows else 0
    return {"rows": rows, "best": best, "best_edge": rows[best]["edge"] if rows else 0.0, "sell_now": now}
