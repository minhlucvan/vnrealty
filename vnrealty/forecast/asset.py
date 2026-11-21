"""One asset's price path: today's value × the area index fan × a local catalyst overlay; and when to sell.

**Value today.** ``value_today`` (an :class:`Estimate` from valuation/pricing) is read as a lognormal whose median is
``value`` and whose [lo, hi] is an 80% band: σ = ln(hi/lo) / (2·1.2816). A zero-width band adds no noise.

**Area.** The fan (:func:`vnrealty.forecast.fan.fan`) is relative to its last observed month L. For a start month S
≥ L and a target T = S + 12·t, the area log-multiplier from S to T has median ln(p50_T / p50_S) and a two-piece normal
spread with σ_down = √(max(0, s↓_T² − s↓_S²)), s↓ = (ln p50 − ln p10)/1.2816 (likewise up with p90): what is already
realised by S is not counted again. A year whose target lies beyond the fan has ``p50: None`` and a reason.

**Catalysts — the double-counting rule.** An area index already prices what the market knows about catalysts that
lift the whole area. So by default only catalysts flagged ``local: True`` (the asset is affected *more than the area
average*: within about 1 km of a new road, or a private-access change) are overlaid, and each one's overlay uplift is
its own effective uplift (after distance decay, :func:`vnrealty.projection.catalysts.effective_uplift`) **minus**
``area_uplift`` — the uplift the same catalyst gives the average of the area the index covers. A local catalyst
without ``area_uplift`` is skipped with the reason (the split is a judgement that must be stated, ``0`` is allowed for
a genuinely private effect). Non-local catalysts are skipped as "already in the area index". With
``include_area_catalysts=True`` every catalyst is overlaid at its full effective uplift, and the result is labelled
as possibly double counting. The overlay's expected path comes from :func:`vnrealty.projection.catalysts.paths`;
the quantiles draw each catalyst landing with its chance ``p`` and ramping in with
:func:`vnrealty.projection.catalysts.ramp`.

Units: VND; months ``YYYY-MM``; rates fractions.
"""
from __future__ import annotations

import math
import random

from vnrealty.forecast.series import month_diff, month_add
from vnrealty.projection.catalysts import effective_uplift, hold_vs_sell, paths, ramp
from vnrealty.stats import quantile
from vnrealty.types import Estimate, Insufficient

__all__ = ["project_asset", "overlay_catalysts", "sell_timing"]

Z90 = 1.2815515655446004


def overlay_catalysts(catalysts: list[dict], include_area_catalysts: bool = False) -> tuple[list[dict], list[dict]]:
    """Apply the double-counting rule. Returns ``(used, skipped)``; each used dict is a copy with ``uplift`` set to
    the net overlay uplift (fraction) and no distance fields (decay is already applied)."""
    used, skipped = [], []
    for i, c in enumerate(catalysts):
        cid = c.get("id", str(i))
        eff = effective_uplift(c)
        if include_area_catalysts:
            used.append({**{k: v for k, v in c.items() if k not in ("distance_km", "decay_km")}, "id": cid,
                         "uplift": eff, "gross_uplift": eff, "area_uplift": None,
                         "note": "full uplift overlaid: may double count what the area index already prices"})
        elif not c.get("local"):
            skipped.append({"id": cid, "reason": "not local: already reflected in the area index"})
        elif c.get("area_uplift") is None:
            skipped.append({"id": cid, "reason": "local but area_uplift missing: cannot separate the local effect"})
        else:
            net = eff - float(c["area_uplift"])
            used.append({**{k: v for k, v in c.items() if k not in ("distance_km", "decay_km")}, "id": cid,
                         "uplift": max(net, -0.95), "gross_uplift": eff, "area_uplift": float(c["area_uplift"])})
    return used, skipped


def _sd(fan: dict, idx: int) -> tuple[float, float, float]:
    """(ln p50, σ_down, σ_up) at fan index ``idx`` (−1 = the last observed month: zero spread)."""
    if idx < 0:
        return math.log(fan["last_value"]), 0.0, 0.0
    p10, p50, p90 = fan["p10"][idx], fan["p50"][idx], fan["p90"][idx]
    return math.log(p50), (math.log(p50) - math.log(p10)) / Z90, (math.log(p90) - math.log(p50)) / Z90


def project_asset(value_today: Estimate | Insufficient, area_fan: dict | Insufficient, local_catalysts: list[dict],
                  years: int, start_month: str, include_area_catalysts: bool = False, n: int = 2000,
                  seed: int = 7) -> dict | Insufficient:
    """Yearly p10/p50/p90 (VND) for t = 0..``years`` from ``start_month`` (see module doc).

    Returns ``{start_month, rows: [{t, year, month, p10, p50, p90, area_mult_p50, overlay_expected, note}],
    months, horizons, p10, p50, p90 (lists over t ≥ 1 with a value, for record.record), catalysts_used,
    catalysts_skipped, rule, value_sigma, n, seed}``.
    """
    if isinstance(value_today, Insufficient):
        return Insufficient("project_asset", "no value today: " + value_today.reason)
    if isinstance(area_fan, Insufficient):
        return Insufficient("project_asset", "no area fan: " + area_fan.reason, area_fan.detail)
    if value_today.value <= 0:
        return Insufficient("project_asset", "value today is not positive")
    off = month_diff(area_fan["last_month"], start_month)
    if off < 0:
        return Insufficient("project_asset", f"start month {start_month} is before the fan's last month "
                                             f"{area_fan['last_month']}")
    sig = (math.log(value_today.hi / value_today.lo) / (2 * Z90)
           if value_today.lo and value_today.lo > 0 and value_today.hi > value_today.lo else 0.0)
    used, skipped = overlay_catalysts(local_catalysts or [], include_area_catalysts)
    y0 = int(start_month[:4])
    exp_overlay = paths({"y1": 0.0, "later": 0.0}, used, years, y0)["base"] if used else [1.0] * (years + 1)
    rng = random.Random(seed)
    hmax = len(area_fan["p50"])
    s_mu, s_dn, s_up = _sd(area_fan, off - 1)
    rows, rec = [], {"months": [], "horizons": [], "p10": [], "p50": [], "p90": []}
    for t in range(years + 1):
        month = month_add(start_month, 12 * t)
        idx = off + 12 * t - 1
        if idx >= hmax:
            rows.append({"t": t, "year": y0 + t, "month": month, "p10": None, "p50": None, "p90": None,
                         "note": f"beyond the area fan ({hmax} months from {area_fan['last_month']})"})
            continue
        mu, dn, up = _sd(area_fan, idx)
        dmu, ddn, dup = mu - s_mu, math.sqrt(max(0.0, dn * dn - s_dn * s_dn)), math.sqrt(max(0.0, up * up - s_up * s_up))
        draws = []
        for _ in range(n):
            z = rng.gauss(0, 1)
            area = dmu + z * (ddn if z < 0 else dup)
            lift = 1.0
            for c in used:
                if rng.random() < float(c["p"]):
                    lift *= 1 + c["uplift"] * ramp(c, t, y0)
            draws.append(value_today.value * math.exp(rng.gauss(0, sig) + area) * lift)
        q = [quantile(draws, p) for p in (0.1, 0.5, 0.9)]
        rows.append({"t": t, "year": y0 + t, "month": month, "p10": q[0], "p50": q[1], "p90": q[2],
                     "area_mult_p50": math.exp(dmu), "overlay_expected": exp_overlay[t]})
        if t >= 1:
            rec["months"].append(month)
            rec["horizons"].append(month_diff(start_month, month))
            for k, v in zip(("p10", "p50", "p90"), q):
                rec[k].append(v)
    rule = ("all catalysts overlaid at full uplift (may double count the area index)" if include_area_catalysts else
            "only local catalysts, net of their area-average uplift; the rest is in the area index")
    return {"start_month": start_month, "rows": rows, **rec, "catalysts_used": used, "catalysts_skipped": skipped,
            "rule": rule, "value_sigma": sig, "n": n, "seed": seed, "fan_last_month": area_fan["last_month"]}


def sell_timing(projection: dict, sell_cost: float, deposit_rate: float, holding_cost: float = 0.0,
                share: float = 1.0) -> dict | Insufficient:
    """Take-home per year from selling at the projected p50 versus selling now and keeping the money on deposit
    (:func:`vnrealty.projection.catalysts.hold_vs_sell`), plus the same edge on the p10 and p90 paths.

    ``sell_cost`` fraction of price (tax + fees), ``deposit_rate`` fraction per year, ``holding_cost`` VND per year for
    the whole property. Years without a projection end the path. ``best`` is the year index of the largest p50 edge.
    """
    if isinstance(projection, Insufficient):
        return Insufficient("sell_timing", projection.reason)
    rows = []
    for r in projection["rows"]:
        if r["p50"] is None:
            break
        rows.append(r)
    if not rows:
        return Insufficient("sell_timing", "no projected year")
    p0 = rows[0]["p50"]
    y0 = rows[0]["year"]
    out = {}
    for key in ("p50", "p10", "p90"):
        out[key] = hold_vs_sell(p0, share, sell_cost, deposit_rate, [r[key] / p0 for r in rows], holding_cost, y0)
    best = out["p50"]["best"]
    return {"rows": [{**r, "edge_p10": out["p10"]["rows"][i]["edge"], "edge_p90": out["p90"]["rows"][i]["edge"]}
                     for i, r in enumerate(out["p50"]["rows"])],
            "best": best, "best_year": out["p50"]["rows"][best]["year"], "best_edge": out["p50"]["best_edge"],
            "sell_now": out["p50"]["sell_now"],
            "note": "edge = take-home − deposit; p10/p90 edges show the downside and upside of holding"}
