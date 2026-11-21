"""Combine independent valuation methods into one estimate.

central = Σ wᵢ·valueᵢ / Σ wᵢ over the methods that produced a number; the range spans every band (min lo, max hi),
so disagreement between methods widens the answer instead of being averaged away. ``Insufficient`` inputs are listed
in ``detail['insufficient']`` with their reasons.

Weights are earned: :func:`method_weights` turns the calibration record into inverse-MAPE weights, shrunk toward
equal weights while the record is thin. Units: VND.
"""
from __future__ import annotations

import sqlite3

from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation import calibrate

__all__ = ["combine", "method_weights"]


def combine(estimates: list[Estimate | Insufficient], weights: dict[str, float] | None = None) -> Estimate | Insufficient:
    """Weighted central (VND) with a range spanning all component bands.

    ``weights`` maps method → weight (≥ 0); a method missing from it gets the mean of the given weights (recorded).
    ``Insufficient`` when no component produced a number or all weights are zero.
    """
    good = [e for e in estimates if isinstance(e, Estimate)]
    bad = [{"method": e.method, "reason": e.reason} for e in estimates if isinstance(e, Insufficient)]
    if not good:
        return Insufficient("triangulated", "no method produced a value", {"insufficient": bad})
    filled = []
    if weights:
        mean_w = sum(weights.values()) / len(weights)
        ws = []
        for e in good:
            if e.method in weights:
                ws.append(max(0.0, float(weights[e.method])))
            else:
                ws.append(mean_w)
                filled.append(e.method)
    else:
        ws = [1.0] * len(good)
    tot = sum(ws)
    if tot <= 0:
        return Insufficient("triangulated", "all weights are zero", {"insufficient": bad})
    v = sum(w * e.value for w, e in zip(ws, good)) / tot
    lo, hi = min(e.lo for e in good), max(e.hi for e in good)
    as_ofs = sorted({e.as_of for e in good if e.as_of})
    return Estimate("triangulated", v, min(lo, v), max(hi, v), n=sum(e.n for e in good),
                    as_of=as_ofs[-1] if as_ofs else None,
                    detail={"components": [{"method": e.method, "value": e.value, "lo": e.lo, "hi": e.hi, "n": e.n,
                                            "weight": w / tot} for w, e in zip(ws, good)],
                            "insufficient": bad, "weights_filled_with_mean": filled,
                            "spread": (max(e.value for e in good) / min(e.value for e in good) - 1)
                            if min(e.value for e in good) > 0 else None})


def method_weights(con: sqlite3.Connection, as_of: str, methods: list[str] | None = None,
                   shrink_n: float = 10.0, mape_floor: float = 0.02) -> dict[str, float]:
    """Weights per method (sum 1) from the calibration record at ``as_of``.

    raw ∝ 1 / max(MAPE, ``mape_floor``); each method's weight = λ·raw_share + (1 − λ)·equal_share with
    λ = n_eff / (n_eff + ``shrink_n``) (sale truths count 1, haircut-asking truths 0.5). Methods without a record get
    λ = 0. ``methods`` defaults to every method in the valuation table.
    """
    sc = calibrate.score(con, as_of)
    if methods is None:
        methods = sorted({r[0] for r in con.execute("SELECT DISTINCT method FROM valuation WHERE method != 'triangulated'")})
    if not methods:
        return {}
    eq = 1.0 / len(methods)
    inv = {m: 1.0 / max(sc[m]["mape"], mape_floor) for m in methods if m in sc}
    tot_inv = sum(inv.values())
    w = {}
    for m in methods:
        if m in sc and tot_inv > 0:
            lam = sc[m]["n_eff"] / (sc[m]["n_eff"] + shrink_n)
            # raw share among the scored methods, scaled to the scored methods' equal mass
            raw = inv[m] / tot_inv * (len(inv) * eq)
            w[m] = lam * raw + (1 - lam) * eq
        else:
            w[m] = eq
    s = sum(w.values())
    return {m: x / s for m, x in w.items()}
