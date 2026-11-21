"""Who is investing: an :class:`InvestorProfile`, the limits it implies, and a questionnaire a skill can ask.

:func:`profile_constraints` turns a profile into the numbers :mod:`vnrealty.strategy.evaluate` and
:mod:`vnrealty.strategy.allocate` enforce. A field left ``None`` takes the risk-tolerance preset in :data:`PRESETS`;
**every preset value is judgement** (the desk's prior for a Vietnamese individual investor), stated here so it can
be argued with. Strategy eligibility:

* ``conservative`` excludes ``fix_flip``, ``rental_arbitrage`` and ``subdivide`` (execution and legal risk);
* ``passive`` time excludes everything that must be operated or built (flip, homestay, CHDV, arbitrage, build,
  subdivide); ``part_time`` excludes ``buy_to_homestay`` and ``rental_arbitrage`` (nightly operations);
* ``strategies_allowed`` (when given) is the whole list, and naming a strategy there re-admits it over both rules —
  the investor's explicit choice wins ("unless allowed").

Money VND, shares fractions of investable wealth, durations months unless named ``_years``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = ["InvestorProfile", "PRESETS", "profile_constraints", "QUESTIONS", "profile_from_answers", "reserve_cash"]

_ALL = ["buy_hold", "buy_rent_long", "build_to_rent", "fix_flip", "land_bank", "subdivide", "rental_arbitrage",
        "joint_venture", "buy_to_homestay", "buy_to_chdv"]

#: risk tolerance -> preset limits (judgement). risk_budget_share = aggregate bear-case loss / cash;
#: max_avg_exit_months = capital-weighted mean liquidity of the chosen set; weights override evaluate's score weights.
PRESETS: dict[str, dict] = {
    "conservative": {"max_ltv": 0.5, "min_dscr": 1.4, "min_liquidity_months": 12, "max_single_asset_share": 0.5,
                     "max_ward_share": 0.6, "max_ptype_share": 0.7, "risk_budget_share": 0.10,
                     "max_avg_exit_months": 9, "excluded": {"fix_flip", "rental_arbitrage", "subdivide"},
                     "weights": {"w_bear": 1.0, "w_ploss": 0.5}},
    "balanced": {"max_ltv": 0.6, "min_dscr": 1.25, "min_liquidity_months": 6, "max_single_asset_share": 0.6,
                 "max_ward_share": 0.7, "max_ptype_share": 0.8, "risk_budget_share": 0.20,
                 "max_avg_exit_months": 12, "excluded": set(), "weights": {}},
    "aggressive": {"max_ltv": 0.7, "min_dscr": 1.1, "min_liquidity_months": 3, "max_single_asset_share": 0.8,
                   "max_ward_share": 0.9, "max_ptype_share": 1.0, "risk_budget_share": 0.35,
                   "max_avg_exit_months": 24, "excluded": set(), "weights": {"w_bear": 0.25, "w_ploss": 0.1}},
}

_TIME_EXCLUDED = {
    "passive": {"fix_flip", "buy_to_homestay", "buy_to_chdv", "rental_arbitrage", "build_to_rent", "subdivide"},
    "part_time": {"buy_to_homestay", "rental_arbitrage"},
    "active": set(),
}


@dataclass(frozen=True)
class InvestorProfile:
    """The investor. ``None`` = take the risk-tolerance preset (judgement)."""
    risk_tolerance: str = "balanced"                 # conservative | balanced | aggressive
    time_available: str = "part_time"                # passive | part_time | active
    max_ltv: float | None = None                     # loan / price
    min_dscr: float | None = None                    # stabilised NOI / debt service, income strategies with debt
    min_liquidity_months: float | None = None        # cash reserve kept aside, in months of monthly_outgoings
    monthly_outgoings: float | None = None           # VND per month: living + existing debt (for the reserve)
    hurdle: float | None = None                      # annual required return
    horizon_years: float | None = None               # longest hold the investor accepts; None = no limit
    max_single_asset_share: float | None = None      # one candidate's peak cash / investable wealth
    max_ward_share: float | None = None
    max_ptype_share: float | None = None
    risk_budget_share: float | None = None           # Σ bear-case loss / cash
    max_avg_exit_months: float | None = None
    strategies_allowed: tuple | None = None          # explicit list; overrides the exclusion rules


def profile_constraints(profile: InvestorProfile) -> dict:
    """Limits implied by ``profile``: ``allowed`` (strategy names), ``excluded`` ({name: reason}), ``max_ltv``,
    ``min_dscr``, ``hurdle``, ``max_hold_months`` (None = no limit), ``min_liquidity_months``, ``monthly_outgoings``,
    the four concentration/risk shares, ``max_avg_exit_months`` and score ``weights`` overrides. Raises
    ``ValueError`` on an unknown tolerance, time or strategy name."""
    if profile.risk_tolerance not in PRESETS:
        raise ValueError(f"risk_tolerance must be one of {sorted(PRESETS)}, got {profile.risk_tolerance!r}")
    if profile.time_available not in _TIME_EXCLUDED:
        raise ValueError(f"time_available must be one of {sorted(_TIME_EXCLUDED)}, got {profile.time_available!r}")
    pre = PRESETS[profile.risk_tolerance]
    excluded: dict[str, str] = {}
    if profile.strategies_allowed is not None:
        unknown = [s for s in profile.strategies_allowed if s not in _ALL]
        if unknown:
            raise ValueError(f"unknown strategies in strategies_allowed: {unknown}")
        for s in _ALL:
            if s not in profile.strategies_allowed:
                excluded[s] = "not in strategies_allowed"
    else:
        for s in _ALL:
            if s in pre["excluded"]:
                excluded[s] = f"excluded for a {profile.risk_tolerance} profile"
            elif s in _TIME_EXCLUDED[profile.time_available]:
                excluded[s] = f"needs more time than '{profile.time_available}'"

    def pick(name):
        v = getattr(profile, name)
        return pre[name] if v is None else v
    return {
        "allowed": [s for s in _ALL if s not in excluded], "excluded": excluded,
        "max_ltv": pick("max_ltv"), "min_dscr": pick("min_dscr"), "hurdle": profile.hurdle,
        "max_hold_months": None if profile.horizon_years is None else profile.horizon_years * 12,
        "min_liquidity_months": pick("min_liquidity_months"), "monthly_outgoings": profile.monthly_outgoings,
        "max_single_asset_share": pick("max_single_asset_share"), "max_ward_share": pick("max_ward_share"),
        "max_ptype_share": pick("max_ptype_share"), "risk_budget_share": pick("risk_budget_share"),
        "max_avg_exit_months": pick("max_avg_exit_months"), "weights": dict(pre["weights"]),
        "basis": "presets are judgement (vnrealty/strategy/profile.py PRESETS)",
    }


def reserve_cash(profile: InvestorProfile) -> float | None:
    """Cash kept aside (VND) = reserve months × ``monthly_outgoings``; ``None`` when outgoings are unknown."""
    c = profile_constraints(profile)
    if profile.monthly_outgoings is None:
        return None
    return c["min_liquidity_months"] * profile.monthly_outgoings


#: The questionnaire: each question maps an answer to profile fields. ``value`` of an option is what is stored.
QUESTIONS: list[dict] = [
    {"id": "risk", "field": "risk_tolerance",
     "question": "Nếu giá trị tài sản giảm 20% trong một năm, bạn sẽ làm gì? / If your property fell 20% in a year?",
     "options": [{"value": "conservative", "label": "Bán để cắt lỗ, mất ngủ / Sell, lose sleep"},
                 {"value": "balanced", "label": "Giữ và chờ / Hold and wait"},
                 {"value": "aggressive", "label": "Mua thêm / Buy more"}]},
    {"id": "time", "field": "time_available",
     "question": "Bạn có bao nhiêu thời gian vận hành mỗi tuần? / Time you can put in each week?",
     "options": [{"value": "passive", "label": "Gần như không / Almost none"},
                 {"value": "part_time", "label": "Vài giờ / A few hours"},
                 {"value": "active", "label": "Như một công việc / Like a job"}]},
    {"id": "horizon", "field": "horizon_years",
     "question": "Bạn có thể để vốn bao lâu? / How long can the money stay invested?",
     "options": [{"value": 2, "label": "≤ 2 năm"}, {"value": 5, "label": "≤ 5 năm"},
                 {"value": 10, "label": "≤ 10 năm"}, {"value": None, "label": "Không giới hạn / No limit"}]},
    {"id": "leverage", "field": "max_ltv",
     "question": "Vay tối đa bao nhiêu phần giá mua? / Largest loan as a share of the price?",
     "options": [{"value": 0.0, "label": "Không vay / No loan"}, {"value": 0.3, "label": "30%"},
                 {"value": 0.5, "label": "50%"}, {"value": 0.7, "label": "70%"}]},
    {"id": "hurdle", "field": "hurdle",
     "question": "Lợi nhuận tối thiểu mỗi năm bạn chấp nhận? / Minimum annual return you accept?",
     "options": [{"value": 0.08, "label": "8%"}, {"value": 0.10, "label": "10%"},
                 {"value": 0.12, "label": "12%"}, {"value": 0.15, "label": "15%"}]},
    {"id": "reserve", "field": "min_liquidity_months",
     "question": "Bạn muốn giữ quỹ dự phòng bao nhiêu tháng chi tiêu? / Months of outgoings kept in reserve?",
     "options": [{"value": 3, "label": "3"}, {"value": 6, "label": "6"}, {"value": 12, "label": "12"}]},
    {"id": "outgoings", "field": "monthly_outgoings", "free": "number",
     "question": "Chi tiêu + trả nợ hiện tại mỗi tháng (VND)? / Monthly living spend + debt payments (VND)?",
     "options": []},
]


def profile_from_answers(answers: dict) -> InvestorProfile:
    """Build a profile from ``{question_id: value}``. Unanswered questions leave the field at its default (presets);
    a value not among a question's options raises ``ValueError`` (free-number questions take any number ≥ 0)."""
    p = InvestorProfile()
    by_id = {q["id"]: q for q in QUESTIONS}
    changes = {}
    for qid, v in answers.items():
        q = by_id.get(qid)
        if q is None:
            raise ValueError(f"unknown question {qid!r}")
        if q.get("free") == "number":
            if not isinstance(v, (int, float)) or v < 0:
                raise ValueError(f"{qid}: expected a number ≥ 0, got {v!r}")
        elif v not in [o["value"] for o in q["options"]]:
            raise ValueError(f"{qid}: {v!r} is not one of the options")
        changes[q["field"]] = v
    return replace(p, **changes)
