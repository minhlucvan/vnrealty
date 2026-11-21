"""A graded verdict from library outputs: each component scored 0–100 by a stated formula, weighted, banded.

``grade(components, weights=None)``. Components (all numbers come from other libraries; nothing is estimated here):

==============  =========================================  ==================================================
component       input                                       sub-score (clamped to 0–100)
==============  =========================================  ==================================================
value_gap *     {estimate, ask, lo?, hi?} (VND)             gap = (estimate − ask) / ask; 50 + 250·gap
                                                            (+20% → 100, −20% → 0); with a band, the distance
                                                            from 50 is shrunk by min(1, 0.15 / half-width),
                                                            half-width = (hi − lo) / 2 / estimate
irr *           {irr, hurdle}                               50 + 500·(irr − hurdle)  (±10 points → 100 / 0)
yield           {yield, ward_median}                        50 + 100·(yield / ward_median − 1)
ev              {p_loss}                                    100·(1 − p_loss / 0.5)   (P(loss) ≥ 50% → 0)
risk            {flags: [{severity}]}                       100 − Σ penalty (high 30, medium 15, low 5)
legal           {status: clear | open | issue}              100 / 50 / 0
liquidity       {days_to_sell}                              100 at ≤ 30 days, 0 at ≥ 365, linear between
==============  =========================================  ==================================================

\\* **core**: a missing (or ``None``) value_gap or irr withholds the grade — ``status='incomplete'`` — instead of
scoring it as zero. Optional components that are missing are left out and the remaining weights renormalised; the
result lists them. Default weights are :data:`WEIGHTS` (judgement; pass ``weights`` to change). **A legal
'issue' caps the total at 39** (letter D at best): an unfixable title is not offset by a good price.

Bands: A+ ≥ 85, A ≥ 70, B ≥ 55, C ≥ 40, D ≥ 25, F otherwise.
"""
from __future__ import annotations

__all__ = ["grade", "WEIGHTS", "CORE", "BANDS", "letter", "SEVERITY_PENALTY"]

WEIGHTS: dict[str, float] = {"value_gap": 0.25, "irr": 0.25, "ev": 0.15, "yield": 0.10, "risk": 0.10, "legal": 0.10,
                             "liquidity": 0.05}
CORE = ("value_gap", "irr")
BANDS = [(85, "A+"), (70, "A"), (55, "B"), (40, "C"), (25, "D")]
SEVERITY_PENALTY = {"high": 30, "medium": 15, "low": 5}
LEGAL_SCORE = {"clear": 100, "open": 50, "issue": 0}
LEGAL_ISSUE_CAP = 39.0


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def letter(score: float) -> str:
    """Letter band for a 0–100 score."""
    for lo, l in BANDS:
        if score >= lo:
            return l
    return "F"


def _value_gap(c: dict) -> dict | None:
    est, ask = c.get("estimate"), c.get("ask")
    if est is None or not ask:
        return None
    gap = (est - ask) / ask
    s = 50 + 250 * gap
    shrink = 1.0
    lo, hi = c.get("lo"), c.get("hi")
    if lo is not None and hi is not None and est:
        hw = (hi - lo) / 2 / est
        if hw > 0:
            shrink = min(1.0, 0.15 / hw)
            s = 50 + (s - 50) * shrink
    out = {"score": _clamp(s), "gap": gap, "estimate": est, "ask": ask, "band_shrink": shrink}
    if lo is not None and hi is not None:
        out["ask_vs_band"] = "below" if ask < lo else "above" if ask > hi else "inside"
    return out


def _irr(c: dict) -> dict | None:
    irr, h = c.get("irr"), c.get("hurdle")
    if irr is None or h is None:
        return None
    return {"score": _clamp(50 + 500 * (irr - h)), "irr": irr, "hurdle": h, "spread": irr - h}


def _yield(c: dict) -> dict | None:
    y, m = c.get("yield"), c.get("ward_median")
    if y is None or not m:
        return None
    return {"score": _clamp(50 + 100 * (y / m - 1)), "yield": y, "ward_median": m, "ratio": y / m}


def _ev(c: dict) -> dict | None:
    p = c.get("p_loss")
    if p is None:
        return None
    return {"score": _clamp(100 * (1 - p / 0.5)), "p_loss": p}


def _risk(c: dict) -> dict | None:
    fl = c.get("flags")
    if fl is None:
        return None
    pen = sum(SEVERITY_PENALTY.get(f.get("severity", "medium"), 15) for f in fl)
    return {"score": _clamp(100 - pen), "n_flags": len(fl), "penalty": pen,
            "high": sum(1 for f in fl if f.get("severity") == "high")}


def _legal(c: dict) -> dict | None:
    s = c.get("status")
    if s not in LEGAL_SCORE:
        return None
    return {"score": float(LEGAL_SCORE[s]), "status": s}


def _liquidity(c: dict) -> dict | None:
    d = c.get("days_to_sell")
    if d is None:
        return None
    return {"score": _clamp(100 * (365 - d) / (365 - 30)), "days_to_sell": d}


_SCORERS = {"value_gap": _value_gap, "irr": _irr, "yield": _yield, "ev": _ev, "risk": _risk, "legal": _legal,
            "liquidity": _liquidity}


def grade(components: dict, weights: dict | None = None) -> dict:
    """Score and band ``components`` (see the module table). Returns ``status`` ('graded' | 'incomplete'),
    ``score`` (0–100 or None), ``letter``, ``subscores`` with their inputs, ``weights_used``, ``missing`` and a
    ``verdict`` sentence built from the numbers."""
    w = dict(WEIGHTS if weights is None else weights)
    unknown = set(components) - set(_SCORERS)
    if unknown:
        raise ValueError(f"unknown components: {sorted(unknown)}")
    subs, missing = {}, []
    for k in _SCORERS:
        c = components.get(k)
        r = _SCORERS[k](c) if isinstance(c, dict) else None
        if r is None:
            missing.append(k)
        else:
            subs[k] = r
    core_missing = [k for k in CORE if k in missing]
    if core_missing:
        return {"status": "incomplete", "score": None, "letter": None, "subscores": subs, "missing": missing,
                "weights_used": {}, "verdict": "No grade: missing core input(s) " + ", ".join(core_missing) + "."}
    used = {k: w.get(k, 0.0) for k in subs if w.get(k, 0.0) > 0}
    tw = sum(used.values())
    if tw <= 0:
        raise ValueError("weights give no weight to any present component")
    used = {k: v / tw for k, v in used.items()}
    score = sum(subs[k]["score"] * v for k, v in used.items())
    capped = False
    if subs.get("legal", {}).get("status") == "issue" and score > LEGAL_ISSUE_CAP:
        score, capped = LEGAL_ISSUE_CAP, True
    L = letter(score)
    parts = []
    vg = subs["value_gap"]
    parts.append(f"estimate {vg['gap']:+.1%} vs ask" + (f" (ask {vg['ask_vs_band']} the band)" if "ask_vs_band" in vg else ""))
    ir = subs["irr"]
    parts.append(f"IRR {ir['irr']:.1%} vs hurdle {ir['hurdle']:.1%}")
    if "yield" in subs:
        parts.append(f"yield {subs['yield']['yield']:.1%} vs ward median {subs['yield']['ward_median']:.1%}")
    if "ev" in subs:
        parts.append(f"P(loss) {subs['ev']['p_loss']:.0%}")
    if "risk" in subs:
        parts.append(f"{subs['risk']['n_flags']} risk flag(s), {subs['risk']['high']} high")
    if "legal" in subs:
        parts.append(f"legal {subs['legal']['status']}")
    if "liquidity" in subs:
        parts.append(f"~{subs['liquidity']['days_to_sell']:.0f} days to sell")
    verdict = f"{L} ({score:.0f}/100): " + "; ".join(parts) + "."
    if capped:
        verdict += " Capped at D by an open legal issue."
    if missing:
        verdict += " Not scored: " + ", ".join(missing) + "."
    return {"status": "graded", "score": score, "letter": L, "subscores": subs, "missing": missing,
            "weights_used": used, "legal_capped": capped, "verdict": verdict}
