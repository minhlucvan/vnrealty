"""Side-by-side comparison of candidate deals on the engine's own numbers.

``compare(items)`` takes ``[{"name", "deal": Deal, "est_value"?: VND, "area_m2"?: m², "extra"?: dict}]`` (the area
may also sit in ``extra["area_m2"]``) and returns one normalised row per item plus a rank per metric. Nothing is
computed here beyond ratios of :func:`~vnrealty.deal.engine.analyse` outputs and the inputs:

========================  ======================================================  =========
metric                    definition                                              better
========================  ======================================================  =========
price                     deal.price (VND)                                        lower
price_m2                  price / area_m2 (VND/m²); None without an area          lower
all_in_cost               analyse cost: price·(1+buy_costs)+renovation+build      lower
equity                    analyse cash_in (VND)                                   lower
yield_gross               rent·12 / price                                         higher
yield_on_cost             stabilised NOI·12 / all-in cost                         higher
cash_on_cash              stabilised cash·12 / equity                             higher
dscr                      stabilised NOI / debt service (None = no debt)          higher
irr                       equity IRR (annual)                                     higher
npv                       NPV at the deal's hurdle (VND)                          higher
payback_month             first month cumulative equity cash ≥ 0                  lower
break_even_occupancy      occupancy that covers costs and debt                    lower
value_gap                 (est_value − price) / price; None without est_value     higher
========================  ======================================================  =========

A ``None`` metric is not ranked (rank ``None``) and never ranks ahead of a number. Ties share the better rank.
"""
from __future__ import annotations

from vnrealty.deal.engine import Deal, analyse

__all__ = ["compare", "METRICS"]

METRICS: dict[str, str] = {
    "price": "lower", "price_m2": "lower", "all_in_cost": "lower", "equity": "lower",
    "yield_gross": "higher", "yield_on_cost": "higher", "cash_on_cash": "higher", "dscr": "higher",
    "irr": "higher", "npv": "higher", "payback_month": "lower", "break_even_occupancy": "lower",
    "value_gap": "higher",
}


def _row(item: dict) -> dict:
    d: Deal = item["deal"]
    a = analyse(d)
    extra = item.get("extra") or {}
    area = item.get("area_m2", extra.get("area_m2"))
    est = item.get("est_value")
    return {
        "name": item["name"], "price": d.price,
        "price_m2": d.price / area if area else None,
        "all_in_cost": a["cost"], "equity": a["cash_in"],
        "yield_gross": a["yield_gross"], "yield_on_cost": a["yield_on_cost"], "cash_on_cash": a["cash_on_cash"],
        "dscr": a["stable"]["dscr"], "irr": a["irr"], "npv": a["npv"], "payback_month": a["payback_month"],
        "break_even_occupancy": a["break_even_occupancy"],
        "value_gap": (est - d.price) / d.price if est is not None and d.price else None,
        "est_value": est, "area_m2": area, "passes": a["passes"], "reasons": a["reasons"], "extra": extra,
    }


def compare(items: list[dict]) -> dict:
    """Rows (one per item, see module table) and ``ranks``: ``{metric: [names best→worst]}``; each row also gets
    ``rank: {metric: 1-based rank or None}``. Raises ``ValueError`` on duplicate names."""
    names = [i["name"] for i in items]
    if len(set(names)) != len(names):
        raise ValueError("item names must be unique")
    rows = [_row(i) for i in items]
    ranks: dict[str, list[str]] = {}
    for r in rows:
        r["rank"] = {}
    for m, better in METRICS.items():
        have = [r for r in rows if r[m] is not None]
        have.sort(key=lambda r: r[m], reverse=(better == "higher"))
        ranks[m] = [r["name"] for r in have]
        prev, prev_rank = None, 0
        for i, r in enumerate(have, 1):
            rank = prev_rank if prev is not None and r[m] == prev else i
            r["rank"][m] = rank
            prev, prev_rank = r[m], rank
        for r in rows:
            r["rank"].setdefault(m, None)
    return {"rows": rows, "ranks": ranks, "metrics": dict(METRICS)}
