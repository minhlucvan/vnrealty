"""Scenario expected value for one deal: what it earns across a set of weighted futures, not just the base case.

A **scenario** is ``{"name": str, "p": float, "overrides": {field: value}}``. Each override names a
:class:`~vnrealty.deal.engine.Deal` field and gives either

* an absolute value — ``{"vacancy": 0.2}``;
* a multiplier — ``{"rent": {"x": 0.8}}`` (rent × 0.8);
* an addition — ``{"float_rate": {"add": 0.03}}`` (+3 percentage points).

Integer fields (months, years) are rounded back to ``int``. Unknown fields raise ``ValueError`` — a typo must not
silently become the base case.

:func:`ev` runs :func:`~vnrealty.deal.engine.analyse` per scenario and returns the probability-weighted profit and
NPV (VND), two IRR summaries — the probability-weighted IRR **and** the IRR of the probability-weighted cash flows
(they differ; the second is the return on the average outcome) — P(loss), P(IRR < hurdle) and the worst case.
Probabilities must sum to 1 (±1e-6) or it raises. :func:`kill_triggers` checks an analysis against hard rules.
:func:`default_scenarios` is a documented, judgement-labelled set. Pure and stdlib-only.
"""
from __future__ import annotations

from dataclasses import fields, replace

from .engine import Deal, _schedule, analyse, irr_monthly

__all__ = ["apply_overrides", "equity_flows", "ev", "kill_triggers", "default_scenarios", "RULES"]

_FIELDS = {f.name: f for f in fields(Deal)}


def apply_overrides(deal: Deal, overrides: dict) -> Deal:
    """Return ``deal`` with overrides applied (absolute, ``{'x': m}`` multiplier or ``{'add': a}``)."""
    changes = {}
    for k, v in (overrides or {}).items():
        if k not in _FIELDS:
            raise ValueError(f"unknown Deal field in overrides: {k!r}")
        cur = getattr(deal, k)
        if isinstance(v, dict):
            if set(v) - {"x", "add"} or not v:
                raise ValueError(f"override for {k!r} must be a number, {{'x': m}} or {{'add': a}}: {v!r}")
            new = cur * v.get("x", 1.0) + v.get("add", 0.0)
        else:
            new = v
        if _FIELDS[k].type in ("int", int):
            new = int(round(new))
        changes[k] = new
    return replace(deal, **changes)


def equity_flows(d: Deal) -> list[float]:
    """The owner's monthly equity cash flows (VND; index 0 = today, negative = money in), as ``analyse`` builds them:
    the up-front own money, each month's net cash after debt and own build money, and the net sale at the end."""
    allrows = _schedule(d)
    r0, rows = allrows[0], allrows[1:]
    eq = [-r0["spend"]] + [r["net"] for r in rows]
    eq[-1] += rows[-1]["value"] * (1 - d.sell_costs) - rows[-1]["balance"]
    return eq


def _summary(name: str, p: float, d: Deal, a: dict) -> dict:
    st = a["stable"]
    return {"name": name, "p": p, "profit": a["profit"], "npv": a["npv"], "irr": a["irr"],
            "irr_unlevered": a["irr_unlevered"], "cash_in": a["cash_in"], "peak_cash_out": a["peak_cash_out"],
            "stable_cash": st["cash"], "dscr": st["dscr"], "worst_month_cash": a["worst_month_cash"],
            "passes": a["passes"], "reasons": a["reasons"]}


def ev(deal: Deal, scenarios: list[dict], hurdle: float | None = None) -> dict:
    """Probability-weighted outcome of ``deal`` over ``scenarios``.

    ``hurdle`` (annual fraction) defaults to ``deal.hurdle``; the NPVs are those of ``analyse`` (at each scenario
    deal's own hurdle). Returns ``scenarios`` (per-scenario summary), ``expected_profit`` and ``expected_npv``
    (VND), ``irr_weighted`` (Σ p·IRR; ``None`` when any scenario's IRR is undefined, those listed in
    ``irr_undefined``), ``irr_of_expected_flows`` (IRR of Σ p·cash flow by month), ``p_loss`` (Σ p where profit
    < 0), ``p_irr_below_hurdle`` (an undefined IRR counts as below — conservative), and ``worst`` (lowest NPV).
    """
    if not scenarios:
        raise ValueError("no scenarios")
    total = 0.0
    for s in scenarios:
        p = s.get("p")
        if p is None or p < 0 or p > 1:
            raise ValueError(f"scenario {s.get('name')!r}: p must be in [0, 1], got {p!r}")
        total += p
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"scenario probabilities sum to {total:.6f}, not 1")
    h = deal.hurdle if hurdle is None else hurdle
    out, flows = [], []
    for s in scenarios:
        d = apply_overrides(deal, s.get("overrides") or {})
        a = analyse(d)
        out.append(_summary(s["name"], s["p"], d, a))
        flows.append((s["p"], equity_flows(d)))
    n = max(len(f) for _, f in flows)
    exp_flows = [sum(p * (f[t] if t < len(f) else 0.0) for p, f in flows) for t in range(n)]
    undefined = [r["name"] for r in out if r["irr"] is None]
    worst = min(out, key=lambda r: r["npv"])
    return {
        "hurdle": h, "scenarios": out,
        "expected_profit": sum(r["p"] * r["profit"] for r in out),
        "expected_npv": sum(r["p"] * r["npv"] for r in out),
        "irr_weighted": None if undefined else sum(r["p"] * r["irr"] for r in out),
        "irr_undefined": undefined,
        "irr_of_expected_flows": irr_monthly(exp_flows),
        "p_loss": sum(r["p"] for r in out if r["profit"] < 0),
        "p_irr_below_hurdle": sum(r["p"] for r in out if r["irr"] is None or r["irr"] < h),
        "worst": {"name": worst["name"], "p": worst["p"], "npv": worst["npv"], "profit": worst["profit"],
                  "irr": worst["irr"]},
    }


# rule -> (where the number lives in an analyse() result, comparison, label)
RULES = {
    "dscr_lt": (lambda a: a["stable"]["dscr"], "lt", "stabilised DSCR"),
    "cash_lt": (lambda a: a["stable"]["cash"], "lt", "stabilised monthly cash flow (VND)"),
    "irr_lt": (lambda a: a["irr"], "lt", "equity IRR"),
    "npv_lt": (lambda a: a["npv"], "lt", "NPV at hurdle (VND)"),
    "peak_cash_gt": (lambda a: a["peak_cash_out"], "gt", "peak cash out (VND)"),
    "worst_month_cash_lt": (lambda a: a["worst_month_cash"], "lt", "worst month's cash after opening (VND)"),
    "p_loss_gt": (lambda a: a["p_loss"], "gt", "probability of a loss"),
}


def kill_triggers(analysis: dict, rules: dict) -> list[dict]:
    """Rules that fire on an ``analyse()`` result (or, for ``p_loss_gt``, an ``ev()`` result).

    ``rules`` maps a rule name in :data:`RULES` to its threshold, e.g. ``{'dscr_lt': 1.2, 'cash_lt': 0,
    'irr_lt': 0.08, 'peak_cash_gt': 2e9}``. Each fired trigger is ``{rule, threshold, value, label, detail}``.
    A number the analysis could not produce fires with ``value=None`` (a missing IRR is not a pass) — except a
    DSCR that is ``None`` because there is no debt, which has nothing to cover and does not fire.
    """
    fired = []
    for rule, thr in rules.items():
        if rule not in RULES:
            raise ValueError(f"unknown kill rule {rule!r}; known: {sorted(RULES)}")
        get, op, label = RULES[rule]
        try:
            v = get(analysis)
        except (KeyError, TypeError):
            v = None
        if v is None:
            if rule == "dscr_lt" and "stable" in analysis and not analysis["stable"].get("debt_service"):
                continue
            fired.append({"rule": rule, "threshold": thr, "value": None, "label": label,
                          "detail": f"{label} could not be computed"})
            continue
        if (op == "lt" and v < thr) or (op == "gt" and v > thr):
            word = "below" if op == "lt" else "above"
            fired.append({"rule": rule, "threshold": thr, "value": v, "label": label,
                          "detail": f"{label} {v:,.4g} is {word} {thr:,.4g}"})
    return fired


def default_scenarios(deal: Deal) -> list[dict]:
    """A five-scenario set — **judgement, not data**: probabilities and shocks are the desk's priors, to be replaced
    by market evidence (rent comps, the rate curve, the price index) when it exists.

    * ``base`` p=0.40 — the deal as entered;
    * ``bear`` p=0.20 — rent × 0.85 and price growth −3 points (a soft market);
    * ``bull`` p=0.15 — rent × 1.10 and price growth +2 points;
    * ``rate_shock`` p=0.15 — floating rate +3 points (VN floating mortgages reprice to deposit rate + margin);
    * ``vacancy`` p=0.10 — vacancy +15 points (capped at 0.95).
    """
    return [
        {"name": "base", "p": 0.40, "overrides": {}, "judgement": True},
        {"name": "bear", "p": 0.20, "overrides": {"rent": {"x": 0.85}, "price_growth": {"add": -0.03}}, "judgement": True},
        {"name": "bull", "p": 0.15, "overrides": {"rent": {"x": 1.10}, "price_growth": {"add": 0.02}}, "judgement": True},
        {"name": "rate_shock", "p": 0.15, "overrides": {"float_rate": {"add": 0.03}}, "judgement": True},
        {"name": "vacancy", "p": 0.10, "overrides": {"vacancy": min(0.95, deal.vacancy + 0.15)}, "judgement": True},
    ]
