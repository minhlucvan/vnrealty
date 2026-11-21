"""Household finances: how big a loan and a property this household can carry, and when it can buy.

Banks size a Vietnamese home loan on three tests, and the tightest one binds:

* **DTI** — all monthly debt payments (existing + the new mortgage) ≤ ``max_dti`` × gross monthly income. There is
  no SBV-wide cap; banks typically use ~40%, some up to 50% (``reference/bank_lending.json``, cited);
* **LTV** — loan ≤ ``max_ltv`` × the property's price (banks apply it to their own appraisal, often lower);
* **property DSCR** — for an income property, the loan its own net income carries at ``Deal.dscr_min``
  (``analyse()['loan_max']``).

Cash needed = price × (1 + buy_costs) + renovation + build − loan + an emergency reserve of ``emergency_months``
× (living spend + existing debt payments + the new mortgage payment). The mortgage payment is an annuity at
``mortgage_rate`` over ``term_years``. Money VND per month unless stated, rates annual fractions.

Every required input missing → :class:`~vnrealty.types.Insufficient`, never a default.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from vnrealty.deal.engine import Deal, _pay, analyse
from vnrealty.deal.scale import Scale, scale_run
from vnrealty.types import Insufficient

__all__ = ["Household", "annuity_factor", "affordability", "purchase_plan", "bank_reference"]

_REF = Path(__file__).resolve().parents[2] / "reference" / "bank_lending.json"


def bank_reference() -> dict:
    """The cited bank-lending reference (typical DTI, LTV) from ``reference/bank_lending.json``."""
    return json.loads(_REF.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Household:
    cash: float | None = None                      # liquid savings today
    monthly_income: float | None = None            # gross, all earners on the loan
    monthly_spend: float | None = None             # living costs, excluding debt payments
    existing_debt_payment: float = 0.0             # other loans, per month
    emergency_months: float = 6.0                  # reserve kept aside, in months of outgoings
    max_dti: float | None = None                   # e.g. 0.40 (bank_lending.json: typical 0.40, range 0.40–0.50)
    mortgage_rate: float | None = None             # floating rate the bank will charge
    term_years: float | None = None
    max_ltv: float | None = None                   # e.g. 0.70 of appraised value (judgement; see reference)
    buy_costs: float = 0.015                       # used without a deal: registration 0.5% + notary + broker
    rent_counted: float = 0.0                      # share of the property's collected rent a bank counts as income


_REQUIRED = ["cash", "monthly_income", "monthly_spend", "max_dti", "mortgage_rate", "term_years", "max_ltv"]


def annuity_factor(rate: float, term_years: float) -> float:
    """Monthly payment per 1 VND borrowed at ``rate`` (annual) over ``term_years``."""
    return _pay(1.0, rate, int(round(term_years * 12)))


def affordability(h: Household, deal: Deal | None = None) -> dict | Insufficient:
    """Largest loan and price the household can carry.

    Without ``deal``: ``loan_max_dti`` and the largest ``max_price`` such that the loan stays within both DTI and
    LTV and own cash covers buy costs, the down payment and the reserve; ``binding`` is ``'ltv'`` (cash runs out
    first at full LTV) or ``'dti'`` (income caps the loan). With ``deal``: the three loan limits for that property,
    the binding one, the usable loan (the deal's loan cut to the limit), ``cash_needed`` incl. reserve, ``shortfall``
    and ``feasible``. VND throughout.
    """
    miss = [k for k in _REQUIRED if getattr(h, k) is None]
    if miss:
        return Insufficient("affordability", "missing: " + ", ".join(miss))
    a = annuity_factor(h.mortgage_rate, h.term_years)
    em = h.emergency_months
    base_out = h.monthly_spend + h.existing_debt_payment
    income = h.monthly_income
    an = None
    if deal is not None:
        an = analyse(deal)
        income += h.rent_counted * an["stable"]["collected"]
    pay_cap = h.max_dti * income - h.existing_debt_payment
    loan_dti = max(0.0, pay_cap / a) if a > 0 else 0.0
    out = {"annuity_factor": a, "payment_capacity": max(0.0, pay_cap), "loan_max_dti": loan_dti,
           "income_counted": income, "max_dti": h.max_dti, "max_ltv": h.max_ltv,
           "save_month": h.monthly_income - h.monthly_spend - h.existing_debt_payment}
    if deal is None:
        c = h.cash - em * base_out                       # cash after the reserve on today's outgoings
        if c <= 0:
            return {**out, "max_price": 0.0, "loan": 0.0, "binding": "cash",
                    "note": "cash does not cover the emergency reserve"}
        k = 1 + h.buy_costs - h.max_ltv + em * h.max_ltv * a
        p = c / k if k > 0 else float("inf")
        if h.max_ltv * p <= loan_dti:
            loan, binding = h.max_ltv * p, "ltv"
        else:
            loan, binding = loan_dti, "dti"
            p = (c + loan_dti - em * a * loan_dti) / (1 + h.buy_costs)
        reserve = em * (base_out + loan * a)
        return {**out, "max_price": p, "loan": loan, "payment": loan * a, "binding": binding, "reserve": reserve,
                "cash_needed": p * (1 + h.buy_costs) - loan + reserve}
    limits = {"dti": loan_dti, "ltv": h.max_ltv * deal.price}
    if an["loan_max"] is not None and an["stable"]["noi"] > 0:
        limits["dscr"] = an["loan_max"]
    binding = min(limits, key=limits.get)
    loan_max = limits[binding]
    loan = min(deal.loan, loan_max)
    cost = an["cost"]
    pay = loan * a
    reserve = em * (base_out + pay)
    need = cost - loan + reserve
    return {**out, "limits": limits, "binding": binding, "loan_max": loan_max, "loan": loan,
            "loan_cut": deal.loan > loan_max, "payment": pay, "dti_after": (h.existing_debt_payment + pay) / income,
            "cost": cost, "reserve": reserve, "cash_needed": need, "shortfall": max(0.0, need - h.cash),
            "feasible": h.cash >= need}


def _add_months(start: str, months: int) -> str:
    y, m = int(start[:4]), int(start[5:7])
    t = (y * 12 + m - 1) + months
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def purchase_plan(h: Household, unit_deal: Deal, years: float, start: str | None = None,
                  scale: Scale | None = None) -> dict | Insufficient:
    """Grow a book by repeating ``unit_deal`` with :func:`~vnrealty.deal.scale.scale_run`: starting cash
    ``h.cash``, monthly savings = income − spend − existing debt payments, reserve = ``h.emergency_months``,
    portfolio LTV cap = ``h.max_ltv``. The unit's loan is first cut to this household's loan limit
    (:func:`affordability` with the deal). ``start`` ('YYYY-MM', default this month) dates the first purchase.

    Returns ``first_buy_month`` (0 = now) and ``first_buy_date``, the purchases, the end state, the yearly ladder
    and why purchases were blocked. Note: the ladder re-checks DSCR and LTV but not household DTI for the second
    and later units — read ``dti_note``.
    """
    aff = affordability(h, unit_deal)
    if isinstance(aff, Insufficient):
        return aff
    if years <= 0:
        return Insufficient("purchase_plan", f"years must be > 0, got {years}")
    d = replace(unit_deal, loan=aff["loan"])
    save = aff["save_month"]
    base = scale or Scale()
    s = replace(base, cash0=h.cash, save_month=max(0.0, save), horizon_years=years,
                reserve_months=h.emergency_months, ltv_cap=h.max_ltv)
    r = scale_run(d, s)
    start = start or date.today().strftime("%Y-%m")
    first = r["buys"][0]["month"] if r["buys"] else None
    return {
        "save_month": save, "unit_loan": aff["loan"], "unit_loan_binding": aff["binding"],
        "first_buy_month": first, "first_buy_date": _add_months(start, first) if first is not None else None,
        "n_buys": len(r["buys"]), "buys": [{**b, "date": _add_months(start, b["month"])} for b in r["buys"]],
        "end": r["end"], "years": r["years"], "blocked": r["blocked"], "target_month": r["target_month"],
        "dti_note": "scale_run checks each unit's own DSCR and the portfolio LTV, not household DTI after the first unit",
        "negative_savings": save < 0,
    }
