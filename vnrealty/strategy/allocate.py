"""Allocate limited cash across candidate deals: which subset to do, each at most once.

A **candidate** is a dict ``{id, strategy, peak_cash, ev_npv, p_loss, bear_loss, liquidity_months, ward, ptype}``
(plus optional ``asset``: candidates sharing an ``asset`` are mutually exclusive — one property cannot be both
flipped and held). ``peak_cash``, ``ev_npv`` and ``bear_loss`` are VND (``bear_loss`` ≥ 0, the bear-case loss);
:func:`candidates_from_evaluation` builds them from :func:`vnrealty.strategy.evaluate.evaluate_all`.

The problem (0/1 choice) — maximise Σ ``ev_npv`` subject to:

* **cash**: Σ peak_cash ≤ cash − reserve; reserve = ``min_liquidity_months`` × ``monthly_outgoings`` (profile), or
  the ``reserve`` argument;
* **single asset**: each peak_cash ≤ ``max_single_asset_share`` × W, W = cash + Σ existing values;
* **ward / ptype**: existing exposure + Σ chosen peak_cash in one ward (ptype) ≤ share × W;
* **risk**: Σ bear_loss ≤ ``risk_budget_share`` × cash;
* **liquidity**: capital-weighted mean ``liquidity_months`` of the chosen set ≤ ``max_avg_exit_months``;
* **asset**: at most one candidate per ``asset``.

Candidates with ``ev_npv`` ≤ 0 never help and are set aside. ≤ 18 remaining: exact depth-first enumeration with
bounds. More: greedy by ev_npv / peak_cash, then a repair pass of single swaps (drop one chosen, add one unchosen)
while the objective improves. The report names the **marginal** candidate — the highest-EV one left out — and the
constraints it would break (the binding ones), with each constraint's utilisation.
"""
from __future__ import annotations

from vnrealty.types import Insufficient

from .profile import InvestorProfile, profile_constraints, reserve_cash

__all__ = ["allocate", "candidates_from_evaluation", "EXACT_MAX"]

EXACT_MAX = 18
_FIELDS = ["id", "strategy", "peak_cash", "ev_npv", "p_loss", "bear_loss", "liquidity_months", "ward", "ptype"]


def candidates_from_evaluation(result: dict, opportunity_id: str, ward: str, ptype: str, top: int | None = None) -> list[dict]:
    """Candidates from an ``evaluate_all`` result for one opportunity (all share ``asset = opportunity_id``).
    ``bear_loss`` = max(0, −bear NPV) (VND); ``top`` keeps only the best N ranked rows."""
    rows = result["ranked"][:top] if top else result["ranked"]
    return [{"id": f"{opportunity_id}:{r['strategy']}", "strategy": r["strategy"], "asset": opportunity_id,
             "peak_cash": r["peak_cash"], "ev_npv": r["ev"]["expected_npv"], "p_loss": r["ev"]["p_loss"],
             "bear_loss": max(0.0, -r["ev"]["bear"]["npv"]), "liquidity_months": r["liquidity_months"],
             "ward": ward, "ptype": ptype} for r in rows]


class _Problem:
    def __init__(self, cands, budget, W, cons, existing, cash):
        self.c = cands
        self.budget = budget
        self.W = W
        self.risk_cap = cons["risk_budget_share"] * cash
        self.ward_cap = cons["max_ward_share"] * W
        self.ptype_cap = cons["max_ptype_share"] * W
        self.liq_cap = cons["max_avg_exit_months"]
        self.ex_ward, self.ex_ptype = {}, {}
        for e in existing:
            self.ex_ward[e.get("ward")] = self.ex_ward.get(e.get("ward"), 0.0) + e["value"]
            self.ex_ptype[e.get("ptype")] = self.ex_ptype.get(e.get("ptype"), 0.0) + e["value"]

    def violations(self, idx: list[int]) -> list[str]:
        """Constraint names the set ``idx`` breaks (including the non-monotone liquidity one)."""
        v = self.monotone_violations(idx)
        if idx:
            k = sum(self.c[i]["peak_cash"] for i in idx)
            if k > 0 and sum(self.c[i]["peak_cash"] * self.c[i]["liquidity_months"] for i in idx) / k > self.liq_cap + 1e-9:
                v.append("liquidity")
        return v

    def monotone_violations(self, idx: list[int]) -> list[str]:
        v = []
        if sum(self.c[i]["peak_cash"] for i in idx) > self.budget + 1e-6:
            v.append("cash")
        if sum(self.c[i]["bear_loss"] for i in idx) > self.risk_cap + 1e-6:
            v.append("risk")
        wards, ptypes, assets = dict(self.ex_ward), dict(self.ex_ptype), set()
        for i in idx:
            c = self.c[i]
            wards[c["ward"]] = wards.get(c["ward"], 0.0) + c["peak_cash"]
            ptypes[c["ptype"]] = ptypes.get(c["ptype"], 0.0) + c["peak_cash"]
            a = c.get("asset")
            if a is not None:
                if a in assets and "asset" not in v:
                    v.append("asset")
                assets.add(a)
        if any(x > self.ward_cap + 1e-6 for w, x in wards.items() if any(self.c[i]["ward"] == w for i in idx)):
            v.append("ward")
        if any(x > self.ptype_cap + 1e-6 for p, x in ptypes.items() if any(self.c[i]["ptype"] == p for i in idx)):
            v.append("ptype")
        return v

    def value(self, idx) -> float:
        return sum(self.c[i]["ev_npv"] for i in idx)


def _exact(P: _Problem) -> list[int]:
    n = len(P.c)
    order = sorted(range(n), key=lambda i: -P.c[i]["ev_npv"])
    suffix = [0.0] * (n + 1)
    for k in range(n - 1, -1, -1):
        suffix[k] = suffix[k + 1] + P.c[order[k]]["ev_npv"]
    best = {"v": 0.0, "set": []}

    def dfs(k: int, chosen: list[int], val: float):
        if val > best["v"] + 1e-9 and not P.violations(chosen):
            best["v"], best["set"] = val, list(chosen)
        if k == n or val + suffix[k] <= best["v"] + 1e-9:
            return
        i = order[k]
        chosen.append(i)
        if not P.monotone_violations(chosen):
            dfs(k + 1, chosen, val + P.c[i]["ev_npv"])
        chosen.pop()
        dfs(k + 1, chosen, val)
    dfs(0, [], 0.0)
    return best["set"]


def _greedy(P: _Problem) -> list[int]:
    order = sorted(range(len(P.c)), key=lambda i: -P.c[i]["ev_npv"] / P.c[i]["peak_cash"])
    chosen: list[int] = []
    for i in order:
        if not P.violations(chosen + [i]):
            chosen.append(i)
    improved = True
    while improved:                                    # repair: best improving single swap or add
        improved = False
        out = [i for i in order if i not in chosen]
        best_gain, best_move = 1e-9, None
        for j in out:
            if not P.violations(chosen + [j]) and P.c[j]["ev_npv"] > best_gain:
                best_gain, best_move = P.c[j]["ev_npv"], (None, j)
            for i in chosen:
                trial = [x for x in chosen if x != i] + [j]
                gain = P.c[j]["ev_npv"] - P.c[i]["ev_npv"]
                if gain > best_gain and not P.violations(trial):
                    best_gain, best_move = gain, (i, j)
        if best_move:
            i, j = best_move
            chosen = [x for x in chosen if x != i] + [j]
            improved = True
    return chosen


def allocate(candidates: list[dict], cash: float, profile: InvestorProfile, existing: list[dict] | None = None,
             reserve: float | None = None) -> dict | Insufficient:
    """Choose the subset of ``candidates`` with the highest total expected NPV within cash and the profile's limits.

    ``cash`` is investable cash today (VND); ``existing`` holdings are ``[{ward, ptype, value}]`` (VND), counted in
    the concentration limits and in W. ``reserve`` (VND) overrides the profile's reserve. Returns ``method``
    ('exact' | 'greedy+repair'), ``chosen`` (candidates), ``totals`` (peak_cash, ev_npv, bear_loss,
    avg_liquidity_months, cash_left), ``limits``, ``utilisation`` ({constraint: {used, limit}}), ``marginal``
    (the best left-out candidate and the constraints it breaks, or None), ``binding`` (those constraint names) and
    ``set_aside`` (candidates never considered, with reasons). Insufficient when the reserve cannot be computed.
    """
    cons = profile_constraints(profile)
    if reserve is None:
        reserve = reserve_cash(profile)
        if reserve is None:
            return Insufficient("allocate", "missing: monthly_outgoings on the profile (reserve = min_liquidity_months "
                                            "× monthly_outgoings), or pass reserve")
    existing = existing or []
    W = cash + sum(e["value"] for e in existing)
    budget = cash - reserve
    single_cap = cons["max_single_asset_share"] * W
    pool, aside, seen = [], [], set()
    for c in candidates:
        miss = [k for k in _FIELDS if c.get(k) is None]
        if miss:
            aside.append({"id": c.get("id"), "reason": "missing: " + ", ".join(miss)})
        elif c["id"] in seen:
            aside.append({"id": c["id"], "reason": "duplicate id"})
        elif c["ev_npv"] <= 0:
            aside.append({"id": c["id"], "reason": f"expected NPV {c['ev_npv']:,.0f} ≤ 0"})
        elif c["peak_cash"] <= 0:
            aside.append({"id": c["id"], "reason": "peak cash ≤ 0"})
        elif c["strategy"] in cons["excluded"]:
            aside.append({"id": c["id"], "reason": "profile: " + cons["excluded"][c["strategy"]]})
        elif c["peak_cash"] > single_cap + 1e-6:
            aside.append({"id": c["id"], "reason": f"single_asset: peak cash {c['peak_cash']:,.0f} above "
                                                    f"{cons['max_single_asset_share']:.0%} of wealth ({single_cap:,.0f})"})
        else:
            pool.append(c)
        if c.get("id") is not None:
            seen.add(c["id"])
    P = _Problem(pool, budget, W, cons, existing, cash)
    if budget <= 0 or not pool:
        idx, method = [], "none"
    elif len(pool) <= EXACT_MAX:
        idx, method = _exact(P), "exact"
    else:
        idx, method = _greedy(P), "greedy+repair"
    chosen = [pool[i] for i in idx]
    k = sum(c["peak_cash"] for c in chosen)
    left = sorted((i for i in range(len(pool)) if i not in idx), key=lambda i: -pool[i]["ev_npv"])
    marginal = None
    if left:
        j = left[0]
        broke = P.violations(idx + [j]) if budget > 0 else ["reserve"]
        marginal = {"candidate": pool[j], "breaks": broke}
    elif budget <= 0 and candidates:
        marginal = {"candidate": None, "breaks": ["reserve"]}
    wards, ptypes = dict(P.ex_ward), dict(P.ex_ptype)
    for c in chosen:
        wards[c["ward"]] = wards.get(c["ward"], 0.0) + c["peak_cash"]
        ptypes[c["ptype"]] = ptypes.get(c["ptype"], 0.0) + c["peak_cash"]
    avg_liq = sum(c["peak_cash"] * c["liquidity_months"] for c in chosen) / k if k > 0 else 0.0
    return {
        "method": method, "chosen": chosen,
        "totals": {"peak_cash": k, "ev_npv": sum(c["ev_npv"] for c in chosen),
                   "bear_loss": sum(c["bear_loss"] for c in chosen), "avg_liquidity_months": avg_liq,
                   "cash_left": cash - k, "reserve": reserve},
        "limits": {"budget": budget, "wealth": W, "single_asset": single_cap, "ward": P.ward_cap,
                   "ptype": P.ptype_cap, "risk": P.risk_cap, "avg_liquidity_months": P.liq_cap},
        "utilisation": {"cash": {"used": k, "limit": budget},
                        "risk": {"used": sum(c["bear_loss"] for c in chosen), "limit": P.risk_cap},
                        "ward": {"used": max(wards.values(), default=0.0), "limit": P.ward_cap},
                        "ptype": {"used": max(ptypes.values(), default=0.0), "limit": P.ptype_cap},
                        "liquidity": {"used": avg_liq, "limit": P.liq_cap}},
        "marginal": marginal, "binding": marginal["breaks"] if marginal else [],
        "set_aside": aside,
    }
