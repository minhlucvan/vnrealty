"""What moves the answer, and where does the deal stop working.

* :func:`tornado` — each input swung to a low and a high value, everything else at base; NPV and IRR at both ends,
  sorted by NPV swing (largest first). The subject is either a :class:`~vnrealty.deal.engine.Deal` (inputs are Deal
  fields) or a function ``assumptions -> Deal | StrategyDeal | Insufficient`` (inputs are assumption keys, e.g.
  ``lambda a: catalog.build('buy_hold', opportunity, a)``), so strategy-level inputs like ``after_repair_value``
  or ``master_rent`` can be swung too.
* :func:`break_even` — the value of one input at which the IRR equals the hurdle (or NPV / profit equals a target),
  by bisection: "at what rent / price / rate does this stop working". Returns the margin of safety against today.

Metrics come from :func:`vnrealty.strategy.catalog.metrics` (equal to ``engine.analyse`` for a plain Deal). Money VND,
rates annual fractions.
"""
from __future__ import annotations

from dataclasses import fields, replace
from typing import Callable

from vnrealty.deal.engine import Deal
from vnrealty.types import Insufficient

from .catalog import StrategyDeal, metrics

__all__ = ["tornado", "break_even"]

_DEAL_FIELDS = {f.name: f for f in fields(Deal)}


def _wrap(x) -> StrategyDeal | Insufficient:
    if isinstance(x, Deal):
        return StrategyDeal("deal", x, x.hold_years * 12)
    return x


def _eval(subject, base: dict | None, key: str, v: float, hurdle: float | None):
    if isinstance(subject, (Deal, StrategyDeal)):
        sd = _wrap(subject)
        if key not in _DEAL_FIELDS:
            raise ValueError(f"unknown Deal field {key!r}")
        if _DEAL_FIELDS[key].type in ("int", int):
            v = int(round(v))
        sd = replace(sd, deal=replace(sd.deal, **{key: v}))
    else:
        sd = _wrap(subject({**(base or {}), key: v}))
    if isinstance(sd, Insufficient):
        return sd
    return metrics(sd, hurdle)


def _base(subject, base: dict | None, hurdle):
    sd = _wrap(subject) if isinstance(subject, (Deal, StrategyDeal)) else _wrap(subject(dict(base or {})))
    return sd if isinstance(sd, Insufficient) else metrics(sd, hurdle)


def tornado(subject: Deal | StrategyDeal | Callable, base_assumptions: dict | None, ranges: dict,
            hurdle: float | None = None) -> dict | Insufficient:
    """``ranges`` = ``{input: (low, high)}`` (absolute values in the input's units). Returns ``base`` ({npv, irr})
    and ``rows`` sorted by ``swing`` = |NPV(high) − NPV(low)| (VND), each ``{input, low, high, npv_low, npv_high,
    irr_low, irr_high, swing}``; a row whose end is Insufficient carries ``insufficient`` and sorts last.
    Insufficient when the base case itself is."""
    b = _base(subject, base_assumptions, hurdle)
    if isinstance(b, Insufficient):
        return Insufficient("tornado", "base case: " + b.reason)
    rows = []
    for key, (lo, hi) in ranges.items():
        ml, mh = _eval(subject, base_assumptions, key, lo, hurdle), _eval(subject, base_assumptions, key, hi, hurdle)
        if isinstance(ml, Insufficient) or isinstance(mh, Insufficient):
            bad = ml if isinstance(ml, Insufficient) else mh
            rows.append({"input": key, "low": lo, "high": hi, "insufficient": bad.reason, "swing": -1.0})
            continue
        rows.append({"input": key, "low": lo, "high": hi, "npv_low": ml["npv"], "npv_high": mh["npv"],
                     "irr_low": ml["irr"], "irr_high": mh["irr"], "swing": abs(mh["npv"] - ml["npv"])})
    rows.sort(key=lambda r: -r["swing"])
    return {"base": {"npv": b["npv"], "irr": b["irr"]}, "rows": rows, "hurdle": b["hurdle"]}


def break_even(subject: Deal | StrategyDeal | Callable, field: str, target: str = "irr", value: float | None = None,
               lo: float | None = None, hi: float | None = None, base_assumptions: dict | None = None,
               iters: int = 60) -> dict | Insufficient:
    """The value of ``field`` at which ``target`` ('irr' | 'npv' | 'profit') equals ``value`` (default: the hurdle
    for 'irr', 0 for the others), by bisection on ``[lo, hi]`` (default ``[0, 3 × current]``, or ``[0, 1]`` when
    current is 0). An undefined IRR counts as below any target. Returns ``{field, break_even, current, margin,
    target, value, direction}``: ``margin`` = break_even / current − 1 (how far the input can move before the
    deal stops working; None when current is 0), ``direction`` 'higher_is_better' or 'lower_is_better'.
    Insufficient when the target is not crossed inside the bracket or the subject is Insufficient. Integer Deal
    fields (months, years) are refused (``ValueError``) — bisection needs a continuous input."""
    if target not in ("irr", "npv", "profit"):
        raise ValueError(f"target must be 'irr', 'npv' or 'profit', got {target!r}")
    if isinstance(subject, (Deal, StrategyDeal)):
        d = _wrap(subject).deal
        if field not in _DEAL_FIELDS:
            raise ValueError(f"unknown Deal field {field!r}")
        if _DEAL_FIELDS[field].type in ("int", int):
            raise ValueError(f"{field!r} is an integer field; break_even needs a continuous input")
        current = getattr(d, field)
    else:
        if base_assumptions is None or base_assumptions.get(field) is None:
            return Insufficient("break_even", f"base_assumptions must give {field!r}")
        current = base_assumptions[field]
    b = _base(subject, base_assumptions, None)
    if isinstance(b, Insufficient):
        return Insufficient("break_even", "base case: " + b.reason)
    tv = (b["hurdle"] if target == "irr" else 0.0) if value is None else value
    lo = 0.0 if lo is None else lo
    hi = (3.0 * current if current else 1.0) if hi is None else hi

    def gap(v: float) -> float | None:
        m = _eval(subject, base_assumptions, field, v, None)
        if isinstance(m, Insufficient):
            return None
        x = m[target]
        return float("-inf") if x is None else x - tv
    gl, gh = gap(lo), gap(hi)
    if gl is None or gh is None:
        return Insufficient("break_even", f"{field} at the bracket end is Insufficient")
    if (gl >= 0) == (gh >= 0):
        return Insufficient("break_even", f"{target} does not cross {tv:,.4g} for {field} in [{lo:,.4g}, {hi:,.4g}]",
                            {"lo": lo, "hi": hi})
    a, z, ga = lo, hi, gl
    for _ in range(iters):
        mid = (a + z) / 2
        gm = gap(mid)
        if gm is None:
            return Insufficient("break_even", f"{field}={mid:,.4g} is Insufficient")
        if (gm >= 0) == (ga >= 0):
            a, ga = mid, gm
        else:
            z = mid
    be = (a + z) / 2
    return {"field": field, "break_even": be, "current": current, "margin": (be / current - 1) if current else None,
            "target": target, "value": tv, "direction": "higher_is_better" if gh >= 0 else "lower_is_better"}
