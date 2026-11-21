"""Evaluate every strategy for one opportunity on one engine and one risk basis, and rank them.

For each strategy in :data:`vnrealty.strategy.catalog.STRATEGIES` that the inputs (and the profile) allow:
the base-case :func:`~vnrealty.strategy.catalog.metrics`, a scenario EV (:func:`ev_strategy`, the same arithmetic
as :func:`vnrealty.deal.ev.ev` but on the strategy's own flows — horizon, deposit, JV share), kill triggers
(:func:`vnrealty.deal.ev.kill_triggers`) and a risk-adjusted score.

**Scenarios.** Default: :func:`vnrealty.deal.ev.default_scenarios` of the strategy's deal (judgement), with the
strategy's ``bear_overrides`` from ``reference/strategy_params.json`` merged into the bear scenario (resale-driven
strategies — flip, land bank, subdivide — also lose 10% of the exit value there; judgement). Passing ``scenarios``
uses them unchanged for every strategy.

**Score** (dimensionless; higher is better; weights in ``strategy_params.json`` ``score_weights``, overridden by
the profile's tolerance, then by ``weights``)::

    K      = peak cash (VND), the largest over the scenarios
    score  =  w_eff  · E[NPV] / K                       NPV per VND of capital tied up
            − w_bear · max(0, −NPV_bear) / K            bear-case loss per VND (bear = scenario named 'bear',
                                                        else the worst scenario)
            − w_ploss· P(loss)                          probability-weighted share of scenarios losing money
            − w_liq  · liquidity_months / 12            years to exit (judgement per strategy)
            − w_cx   · (complexity − 1) / 4             execution difficulty 1..5 mapped to 0..1 (judgement)

Ranking: by score, except that a strategy with a fired kill trigger ranks below every strategy without one.
Excluded (with reasons): Insufficient inputs, profile rules (not allowed, LTV above ``max_ltv``, DSCR below
``min_dscr`` for an income strategy with debt, horizon beyond ``horizon_years``), and K ≤ 0 (no capital at risk:
the score is undefined). Money VND, rates annual fractions.
"""
from __future__ import annotations

from dataclasses import replace

from vnrealty.deal.engine import irr_monthly
from vnrealty.deal.ev import apply_overrides, default_scenarios, kill_triggers
from vnrealty.types import Insufficient

from .catalog import STRATEGIES, StrategyDeal, build, complexity, flows, liquidity_months, metrics, params
from .profile import InvestorProfile, profile_constraints

__all__ = ["ev_strategy", "scenarios_for", "score", "evaluate_all", "default_weights"]


def default_weights() -> dict:
    """Score weights from ``strategy_params.json`` (judgement)."""
    return {k: v for k, v in params()["score_weights"].items() if not k.startswith("_")}


def scenarios_for(sd: StrategyDeal) -> list[dict]:
    """``ev.default_scenarios`` of the strategy's deal with its ``bear_overrides`` merged into ``bear``."""
    sc = default_scenarios(sd.deal)
    extra = params()["bear_overrides"].get(sd.strategy)
    if extra:
        sc = [dict(s, overrides={**s["overrides"], **extra}) if s["name"] == "bear" else s for s in sc]
    return sc


def ev_strategy(sd: StrategyDeal, scenarios: list[dict], hurdle: float | None = None) -> dict:
    """Probability-weighted outcome of a strategy deal: each scenario's overrides go to the Deal
    (:func:`~vnrealty.deal.ev.apply_overrides`), the horizon, extra flows and JV share stay. Returns
    ``scenarios`` (per-scenario :func:`metrics`), ``expected_npv``/``expected_profit`` (VND), ``irr_weighted``
    (None if any IRR is undefined), ``irr_of_expected_flows``, ``p_loss``, ``p_irr_below_hurdle`` (undefined IRR
    counts as below), ``worst`` and ``bear`` (the 'bear' scenario, else the worst) and ``peak_cash_max`` (VND).
    For a plain deal this equals :func:`vnrealty.deal.ev.ev`. Raises ``ValueError`` if probabilities ≠ 1."""
    if not scenarios:
        raise ValueError("no scenarios")
    tot = sum(s.get("p", -1) for s in scenarios)
    if any(s.get("p") is None or not 0 <= s["p"] <= 1 for s in scenarios) or abs(tot - 1) > 1e-6:
        raise ValueError(f"scenario probabilities must be in [0, 1] and sum to 1, got {tot}")
    h = sd.deal.hurdle if hurdle is None else hurdle
    out, fl = [], []
    for s in scenarios:
        sd2 = replace(sd, deal=apply_overrides(sd.deal, s.get("overrides") or {}))
        m = metrics(sd2, h)
        out.append({"name": s["name"], "p": s["p"], **m})
        fl.append((s["p"], flows(sd2)))
    n = max(len(f) for _, f in fl)
    exp = [sum(p * (f[t] if t < len(f) else 0.0) for p, f in fl) for t in range(n)]
    worst = min(out, key=lambda r: r["npv"])
    bear = next((r for r in out if r["name"] == "bear"), worst)
    und = [r["name"] for r in out if r["irr"] is None]
    return {"hurdle": h, "scenarios": out,
            "expected_npv": sum(r["p"] * r["npv"] for r in out),
            "expected_profit": sum(r["p"] * r["profit"] for r in out),
            "irr_weighted": None if und else sum(r["p"] * r["irr"] for r in out), "irr_undefined": und,
            "irr_of_expected_flows": irr_monthly(exp),
            "p_loss": sum(r["p"] for r in out if r["profit"] < 0),
            "p_irr_below_hurdle": sum(r["p"] for r in out if r["irr"] is None or r["irr"] < h),
            "worst": {k: worst[k] for k in ("name", "p", "npv", "profit", "irr")},
            "bear": {k: bear[k] for k in ("name", "p", "npv", "profit", "irr")},
            "peak_cash_max": max(r["peak_cash"] for r in out)}


def score(expected_npv: float, peak_cash: float, bear_npv: float, p_loss: float, liq_months: float, cx: float,
          weights: dict) -> dict:
    """The score and its terms (see the module docstring). ``peak_cash`` must be > 0 (VND)."""
    w = weights
    terms = {"efficiency": w["w_eff"] * expected_npv / peak_cash,
             "bear_penalty": -w["w_bear"] * max(0.0, -bear_npv) / peak_cash,
             "loss_penalty": -w["w_ploss"] * p_loss,
             "liquidity_penalty": -w["w_liq"] * liq_months / 12,
             "complexity_penalty": -w["w_cx"] * (cx - 1) / 4}
    return {"score": sum(terms.values()), "terms": terms}


def evaluate_all(opportunity: dict, assumptions: dict | None = None, strategies: list[str] | None = None,
                 scenarios: list[dict] | None = None, hurdle: float | None = None,
                 profile: InvestorProfile | None = None, weights: dict | None = None,
                 kill_rules: dict | None = None) -> dict:
    """Evaluate ``strategies`` (default all) for one opportunity and rank them.

    ``hurdle`` (annual) overrides ``assumptions['hurdle']`` and the profile's; the profile's ``min_dscr`` becomes
    the deals' ``dscr_min``. ``kill_rules`` default to ``{'irr_lt': hurdle, 'p_loss_gt': 0.25}`` plus ``dscr_lt``
    at the profile's ``min_dscr`` when a profile is given. Returns ``ranked`` (rows best first: strategy, score,
    terms, metrics, ev summary, kill, liquidity_months, complexity, peak_cash), ``excluded``
    (``[{strategy, reason}]``), ``weights``, ``hurdle`` and ``formula``.
    """
    a = dict(assumptions or {})
    cons = profile_constraints(profile) if profile is not None else None
    if hurdle is None and cons and cons["hurdle"] is not None and a.get("hurdle") is None:
        hurdle = cons["hurdle"]
    if hurdle is not None:
        a["hurdle"] = hurdle
    if cons:
        a.setdefault("dscr_min", cons["min_dscr"])
    w = {**default_weights(), **(cons["weights"] if cons else {}), **(weights or {})}
    names = strategies or list(STRATEGIES)
    ranked, excluded = [], []
    for name in names:
        if cons and name in cons["excluded"]:
            excluded.append({"strategy": name, "reason": "profile: " + cons["excluded"][name]})
            continue
        sd = build(name, opportunity, a)
        if isinstance(sd, Insufficient):
            excluded.append({"strategy": name, "reason": "insufficient: " + sd.reason, "detail": sd.detail})
            continue
        h = sd.deal.hurdle
        m = metrics(sd, h)
        if cons:
            if cons["max_ltv"] is not None and m["ltv"] > cons["max_ltv"] + 1e-12:
                excluded.append({"strategy": name, "reason": f"profile: LTV {m['ltv']:.0%} above max {cons['max_ltv']:.0%}"})
                continue
            if m["dscr"] is not None and m["dscr"] < cons["min_dscr"]:
                excluded.append({"strategy": name, "reason": f"profile: DSCR {m['dscr']:.2f} below {cons['min_dscr']}"})
                continue
            if cons["max_hold_months"] is not None and m["horizon_months"] > cons["max_hold_months"]:
                excluded.append({"strategy": name, "reason": f"profile: horizon {m['horizon_months']} months beyond "
                                                             f"{cons['max_hold_months']:.0f}"})
                continue
        e = ev_strategy(sd, scenarios if scenarios is not None else scenarios_for(sd), h)
        K = max(m["peak_cash"], e["peak_cash_max"])
        if K <= 0:
            excluded.append({"strategy": name, "reason": "no capital at risk (peak cash ≤ 0): score undefined"})
            continue
        liq, cx = liquidity_months(name), complexity(name)
        sc = score(e["expected_npv"], K, e["bear"]["npv"], e["p_loss"], liq, cx, w)
        rules = dict(kill_rules) if kill_rules is not None else {"irr_lt": h, "p_loss_gt": 0.25}
        if kill_rules is None and cons:
            rules["dscr_lt"] = cons["min_dscr"]
        ana = {"stable": {"dscr": m["dscr"], "debt_service": m["debt_service"], "cash": m["stable_cash"]},
               "irr": m["irr"], "npv": m["npv"], "peak_cash_out": m["peak_cash"],
               "worst_month_cash": m["worst_month_cash"], "p_loss": e["p_loss"]}
        kill = kill_triggers(ana, rules)
        ranked.append({"strategy": name, "score": sc["score"], "terms": sc["terms"], "metrics": m,
                       "ev": {k: v for k, v in e.items() if k != "scenarios"}, "scenarios": e["scenarios"],
                       "kill": kill, "liquidity_months": liq, "complexity": cx, "peak_cash": K,
                       "meta": sd.meta})
    ranked.sort(key=lambda r: (bool(r["kill"]), -r["score"]))
    return {"ranked": ranked, "excluded": excluded, "weights": w, "hurdle": a.get("hurdle"),
            "formula": "score = w_eff·E[NPV]/K − w_bear·max(0,−NPV_bear)/K − w_ploss·P(loss) − w_liq·liq_months/12 "
                       "− w_cx·(complexity−1)/4; K = peak cash; killed strategies rank last"}
