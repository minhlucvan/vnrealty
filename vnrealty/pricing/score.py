"""A 0–100 relative-value score from the metrics of :mod:`vnrealty.pricing.metrics`, with confidence and reasons.

**Points per metric** (0 = expensive / poor, 50 = in line, 100 = cheap / strong), by rule (:data:`RULES`)::

    peer_low   100 − percentile              price per unit vs peers (cheaper = more points)
    ratio_high clamp(50 + 100·(ratio − 1))   ratio = value ÷ benchmark, higher is better (residual ÷ asking,
                                             cost value ÷ asking, income value ÷ asking, yield ÷ ward yield,
                                             net yield ÷ cap rate, triangulated value ÷ asking): ratio 1.5 → 100,
                                             0.5 → 0
    ratio_low  clamp(50 − 100·(ratio − 1))   ratio = value ÷ benchmark, lower is better (price-to-rent multiple
                                             ÷ ward multiple)
    log_resid  clamp(50 − 100·residual)      hedonic log residual: −0.5 → 100, +0.5 → 0

A metric is *computed* when its entry has the number its rule needs (a peer percentile, a ratio, a value) and is
not marked ``independent: False`` (derived only from peer medians — scoring it would double count the price
percentile).

**Score** = Σ wᵢ·pointsᵢ / Σ wᵢ over computed metrics; **confidence** = Σ w(computed) / Σ w(all weighted metrics
of the type). Default weights per type are judgement, in ``reference/pricing_params.json`` ``score_weights``.
The score is **withheld** (``score: None``) when confidence < ``score_min_confidence`` (0.5).

**why**: the three strongest and three weakest scored metrics with their numbers, and **red flags**: giấy tay /
HĐMB title, kiệt narrower than ``min_alley_m``, negotiable price, stale listing (days on market > ``stale_days``),
asking below the official table, and a robust z of the type's key price metric ≤ ``z_too_cheap`` — reported as
"too cheap: verify" (a data error, a defect or a different product is likelier than a gift).
"""
from __future__ import annotations

from .metrics import KEY_METRIC
from .zoning import load_params

__all__ = ["RULES", "points", "pricing_score", "red_flags"]

RULES = {
    "price_m2": "peer_low", "price_m2_floor": "peer_low", "price_per_frontage_m": "peer_low",
    "price_per_room": "peer_low", "price_per_buildable_m2": "peer_low", "rent_m2": "peer_low",
    "residual_vs_asking": "ratio_high", "cost_value_vs_asking": "ratio_high", "income_value_vs_asking": "ratio_high",
    "gross_yield_vs_ward": "ratio_high", "net_yield": "ratio_high", "value_gap": "ratio_high",
    "price_to_rent": "ratio_low", "hedonic_residual": "log_resid",
}


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def points(name: str, entry: dict) -> float | None:
    """Points 0–100 for one metric entry by its rule, or None when it cannot be scored."""
    rule = RULES.get(name)
    if rule is None or not isinstance(entry, dict) or "insufficient" in entry or entry.get("independent") is False:
        return None
    if rule == "peer_low":
        pct = (entry.get("peer") or {}).get("percentile")
        return None if pct is None else _clamp(100.0 - pct)
    if rule in ("ratio_high", "ratio_low"):
        r = entry.get("ratio")
        if r is None:
            return None
        return _clamp(50 + 100 * (r - 1)) if rule == "ratio_high" else _clamp(50 - 100 * (r - 1))
    if rule == "log_resid":
        v = entry.get("value")
        return None if not isinstance(v, (int, float)) else _clamp(50 - 100 * v)
    return None  # pragma: no cover


def _num(entry: dict) -> str:
    v = entry.get("value")
    if isinstance(v, float):
        s = f"{v:,.4g}" if abs(v) < 10 else f"{v:,.0f}"
    else:
        s = str(v)
    extra = ""
    peer = entry.get("peer") or {}
    if peer.get("percentile") is not None:
        extra = f" (p{peer['percentile']:.0f} of {peer['n']} {peer['scope']} peers, median {peer['median']:,.0f})"
    elif entry.get("ratio") is not None and entry.get("unit") != "×":
        extra = f" (ratio {entry['ratio']:.2f})"
    return f"{s} {entry.get('unit', '')}{extra}".strip()


def red_flags(metrics: dict, ptype: str, params: dict | None = None) -> list[str]:
    """Red flags from the metrics (see module docstring)."""
    p = params or load_params()
    flags: list[str] = []
    leg = (metrics.get("legal_status") or {}).get("value")
    if leg == "giay_tay":
        flags.append("legal: giấy tay (handwritten paper) — no certificate; title risk, verify at the land office")
    elif leg == "hdmb":
        flags.append("legal: HĐMB only (no sổ hồng yet) — verify the project's certificate status")
    a = (metrics.get("alley_m") or {}).get("value")
    if isinstance(a, (int, float)) and 0 < a < p["min_alley_m"]["value"]:
        flags.append(f"access: kiệt {a:g} m < {p['min_alley_m']['value']:g} m (no car, fire access, 3-floor cap)")
    if (metrics.get("negotiable") or {}).get("value"):
        flags.append("price: 'thỏa thuận' seen — the stated number may not be the real ask")
    d = (metrics.get("days_on_market") or {}).get("value")
    if isinstance(d, (int, float)) and d > p["stale_days"]["value"]:
        flags.append(f"stale: {d:.0f} days on market (> {p['stale_days']['value']:.0f}) — motivated seller or a "
                     f"reason nobody bought")
    o = metrics.get("official_ratio") or {}
    if isinstance(o.get("value"), (int, float)) and o["value"] < 1:
        flags.append(f"asking/m² is {o['value']:.2f}× the official table — below the state floor; check the lot")
    key = KEY_METRIC.get(ptype)
    z = ((metrics.get(key) or {}).get("peer") or {}).get("z") if key else None
    if z is not None and z <= p["z_too_cheap"]["value"]:
        flags.append(f"too cheap: verify — {key} robust z {z:.1f} vs peers (data error, defect or different product?)")
    return flags


def pricing_score(metrics: dict, ptype: str, weights: dict | None = None, params: dict | None = None) -> dict:
    """Score one listing's metrics (0–100, higher = better relative value).

    ``ptype``: the listing type, or 'rent' for rentals. ``weights`` (metric → weight) replace the type's defaults.
    Returns ``{score (None when withheld), confidence, withheld_reason, sub_scores {metric: {points, weight, value}},
    missing [metrics weighted but not computed, with reason], why {strongest, weakest}, flags, formula}``.
    """
    p = params or load_params()
    w = dict(weights) if weights is not None else {k: v for k, v in p["score_weights"].get(ptype, {}).items()}
    tot = sum(v for v in w.values() if v > 0)
    subs, missing = {}, []
    for name, wt in w.items():
        if wt <= 0:
            continue
        e = metrics.get(name)
        pts = points(name, e) if e is not None else None
        if pts is None:
            reason = ("not produced" if e is None else e.get("insufficient") or
                      ("derived from peer medians only (not independent)" if e.get("independent") is False else
                       "no peer percentile / ratio to score"))
            missing.append({"metric": name, "weight": wt, "reason": reason})
            continue
        subs[name] = {"points": pts, "weight": wt, "value": e.get("value"), "unit": e.get("unit"), "text": _num(e)}
    got = sum(s["weight"] for s in subs.values())
    conf = got / tot if tot > 0 else 0.0
    min_c = p["score_min_confidence"]["value"]
    score = sum(s["weight"] * s["points"] for s in subs.values()) / got if got > 0 else None
    withheld = None
    if tot <= 0:
        withheld, score = f"no weights for type {ptype!r}", None
    elif conf < min_c:
        withheld, score = f"confidence {conf:.2f} < {min_c} (computed weight share)", None
    ranked = sorted(subs.items(), key=lambda kv: -kv[1]["points"])
    strongest = [{"metric": k, "points": round(v["points"], 1), "text": v["text"]} for k, v in ranked[:3]]
    weakest = [{"metric": k, "points": round(v["points"], 1), "text": v["text"]} for k, v in reversed(ranked[-3:])]
    return {"score": score, "confidence": conf, "withheld_reason": withheld, "sub_scores": subs, "missing": missing,
            "why": {"strongest": strongest, "weakest": weakest}, "flags": red_flags(metrics, ptype, p),
            "formula": "score = Σ w·points / Σ w over computed metrics; confidence = computed weight / total weight; "
                       "withheld below " + str(min_c)}
