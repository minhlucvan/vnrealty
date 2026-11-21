"""One real-estate deal, month by month: should it be bought, with how much loan, and what does it earn?

`wealth.property_dcf` values a generic purchase from a yield. This module takes a concrete deal the way a
Vietnamese buyer meets it, in either shape:

* **an existing property** — a price, buying costs, renovation and the months it stands empty, then rent;
* **land plus a building** — the land price, then ``build_cost`` spent evenly over ``build_months`` with nothing
  earned, then income. The building's value can wear out over ``building_life_years`` (its replacement cost
  rising with ``cost_growth``) while the land's grows with ``price_growth``.

Income is either **rent** from a tenant or **a business** run on the site (homestay, café, ...): the same
``rent`` field is then the monthly revenue, which can ramp up over ``ramp_months`` after opening, and costs
include ``cogs`` (a share of revenue) and ``staff`` (a fixed monthly cost) on top of fees, running costs and the
tax on revenue. Running costs start when the building is finished; staff when income starts.

The loan funds the latest spending: own money pays first, the loan is drawn as spending exceeds it, and the loan
is interest-only during construction and any grace months; it has a fixed teaser rate, then a floating rate.
The property is sold after ``hold_years`` with selling costs.

`analyse` returns the money needed, the stabilised monthly picture (income, net operating income, debt service,
cash flow, coverage), the investment metrics (equity and unlevered IRR, NPV at ``hurdle``, money multiple,
payback), the break-even income and occupancy, the largest loan the income can carry at ``dscr_min``, the profit
split into income, interest, appreciation, renovation gain and costs (which sums to the total profit), a
year-by-year table, and a verdict with its reasons. Pure and stdlib-only.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = ["Deal", "analyse", "schedule", "irr_monthly", "stress"]


@dataclass(frozen=True)
class Deal:
    price: float = 3e9                       # the property, or the land
    buy_costs: float = 0.015                 # registration, notary, broker: share of price
    renovation: float = 200e6                # repairs, fit-out, furniture, site preparation
    value_after: float = 3.3e9               # market value of what was bought (property, or land) once ready
    lease_up_months: int = 3                 # empty after it is ready, before income starts
    build_cost: float = 0.0                  # construction, spent evenly over build_months
    build_months: int = 0
    building_life_years: int = 0             # 0 = the building's value moves with price_growth
    loan: float = 1.5e9
    teaser_rate: float = 0.07
    teaser_years: int = 2
    float_rate: float = 0.105
    grace_months: int = 0                    # interest only (construction months are interest-only anyway)
    term_years: int = 20
    rent: float = 25e6                       # per month, today: rent, or business revenue
    rent_growth: float = 0.03
    ramp_months: int = 0                     # income grows linearly to full over these months after opening
    vacancy: float = 0.08
    management: float = 0.05                 # share of income: manager, booking platform
    cogs: float = 0.0                        # share of revenue: ingredients, supplies (business only)
    staff: float = 0.0                       # per month (business only)
    running_costs: float = 2e6               # per month: upkeep, insurance, utilities, fees
    cost_growth: float = 0.035
    rent_tax: float = 0.10                   # tax on the income collected
    price_growth: float = 0.05
    hold_years: int = 10
    sell_costs: float = 0.03                 # 2% tax on the sale price + broker
    hurdle: float = 0.10
    dscr_min: float = 1.2                    # this property's net income / its own payments


def _pay(balance: float, rate: float, months: int) -> float:
    r = rate / 12.0
    if months <= 0:
        return balance
    return balance / months if r == 0 else balance * r / (1.0 - (1.0 + r) ** -months)


def _cost(d: Deal) -> float:
    return d.price * (1 + d.buy_costs) + d.renovation + d.build_cost


def _loan(d: Deal) -> float:
    return max(0.0, min(d.loan, _cost(d)))


def schedule(d: Deal) -> list[dict]:
    """Month by month over the holding period (months 1..hold)."""
    return _schedule(d)[1:]


def _schedule(d: Deal) -> list[dict]:
    """Row 0 is today (the purchase), then months 1..hold."""
    n_term = d.term_years * 12
    loan = _loan(d)
    own = _cost(d) - loan                    # own money, spent first
    spend0 = d.price * (1 + d.buy_costs) + d.renovation + (d.build_cost if d.build_months <= 0 else 0.0)
    eq0 = min(spend0, own)
    own_left = own - eq0
    bal = spend0 - eq0
    rows = [{"month": 0, "spend": eq0, "draw": bal, "balance": bal}]
    io_end = max(d.grace_months, d.build_months)
    open_m = d.build_months + d.lease_up_months
    built = d.build_cost if d.build_months <= 0 else 0.0
    pay = 0.0
    cur_rate = None
    for t in range(1, d.hold_years * 12 + 1):
        spend = draw = 0.0
        if d.build_months > 0 and t <= d.build_months:
            need = d.build_cost / d.build_months
            spend = min(need, own_left)
            own_left -= spend
            draw = need - spend
            bal += draw
            built += need
        rate = d.teaser_rate if t <= d.teaser_years * 12 else d.float_rate
        interest = bal * rate / 12.0
        if bal <= 0:
            payment = 0.0
        elif t <= io_end:
            payment = interest
        else:
            if rate != cur_rate or t == io_end + 1:
                pay = _pay(bal, rate, n_term - (t - 1))
                cur_rate = rate
            payment = min(pay, bal + interest) if t <= n_term else 0.0
        principal = payment - interest if payment > 0 else 0.0
        bal = max(0.0, bal - principal)
        y = (t - 1) // 12
        if t > open_m:
            ramp = min(1.0, (t - open_m) / d.ramp_months) if d.ramp_months > 0 else 1.0
            gross = d.rent * (1 + d.rent_growth) ** y * ramp
        else:
            gross = 0.0
        collected = gross * (1 - d.vacancy)
        fixed = (d.running_costs if t > d.build_months else 0.0) + (d.staff if t > open_m else 0.0)
        opex = collected * (d.management + d.cogs) + fixed * (1 + d.cost_growth) ** y
        tax = collected * d.rent_tax
        noi = collected - opex - tax
        g = (1 + d.price_growth) ** (t / 12.0)
        if d.building_life_years > 0:
            age = max(0, t - d.build_months) / 12.0
            bfac = (1 + d.cost_growth) ** (t / 12.0) * max(0.0, 1.0 - age / d.building_life_years)
        else:
            bfac = g
        value = d.value_after * g + built * bfac
        rows.append({"month": t, "rate": rate, "payment": payment, "interest": interest, "principal": principal,
                     "balance": bal, "rent": gross, "collected": collected, "opex": opex, "tax": tax, "noi": noi,
                     "cash": noi - payment, "spend": spend, "draw": draw, "net": noi - payment - spend,
                     "value": value})
    return rows


def irr_monthly(cfs: list[float]) -> float | None:
    """Annualised IRR of monthly cash flows (index 0 = today)."""
    def npv(r):
        return sum(c / (1.0 + r) ** t for t, c in enumerate(cfs))
    lo, hi = -0.5, 0.5
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    m = (lo + hi) / 2.0
    return (1.0 + m) ** 12 - 1.0


def _stable(d: Deal) -> dict:
    """A full year at full income, today's prices, the floating rate."""
    collected = d.rent * (1 - d.vacancy)
    noi = collected * (1 - d.management - d.cogs - d.rent_tax) - d.running_costs - d.staff
    loan = _loan(d)
    ds = _pay(loan, d.float_rate, d.term_years * 12) if loan > 0 else 0.0
    return {"rent": d.rent, "collected": collected, "noi": noi, "debt_service": ds, "cash": noi - ds,
            "dscr": (noi / ds) if ds > 0 else None}


def analyse(d: Deal) -> dict:
    allrows = _schedule(d)
    r0, rows = allrows[0], allrows[1:]
    cost, loan = _cost(d), _loan(d)
    cash_in = cost - loan
    sale_gross = rows[-1]["value"]
    sale_net = sale_gross * (1 - d.sell_costs) - rows[-1]["balance"]
    eq = [-r0["spend"]] + [r["net"] for r in rows]
    eq[-1] += sale_net
    un = [-(d.price * (1 + d.buy_costs) + d.renovation + (d.build_cost if d.build_months <= 0 else 0.0))]
    un += [r["noi"] - r["spend"] - r["draw"] for r in rows]
    un[-1] += sale_gross * (1 - d.sell_costs)
    irr = irr_monthly(eq)
    mh = (1 + d.hurdle) ** (1 / 12) - 1
    npv = sum(c / (1 + mh) ** t for t, c in enumerate(eq))
    st = _stable(d)
    share = 1 - d.management - d.cogs - d.rent_tax
    fixed = d.running_costs + d.staff + st["debt_service"]
    k = (1 - d.vacancy) * share
    be_rent = fixed / k if k > 0 else None
    be_occ = fixed / (d.rent * share) if d.rent * share > 0 else None
    ann = _pay(1.0, d.float_rate, d.term_years * 12)
    loan_max = max(0.0, st["noi"] / d.dscr_min / ann) if d.dscr_min > 0 and ann > 0 else None
    cum, payback = -r0["spend"], None
    for r in rows:
        cum += r["net"]
        if payback is None and cum >= 0:
            payback = r["month"]
    interest = sum(r["interest"] for r in rows if r["payment"] > 0)
    split = {
        "rent": sum(r["noi"] for r in rows),
        "interest": -interest,
        "appreciation": sale_gross - d.value_after - d.build_cost,
        "renovation_gain": d.value_after - d.price - d.renovation,
        "costs": -(d.price * d.buy_costs + sale_gross * d.sell_costs),
    }
    years = []
    for y in range(d.hold_years):
        rs = rows[y * 12:(y + 1) * 12]
        years.append({"year": y + 1, "rent": sum(r["collected"] for r in rs), "opex": sum(r["opex"] + r["tax"] for r in rs),
                      "noi": sum(r["noi"] for r in rs), "debt_service": sum(r["payment"] for r in rs),
                      "interest": sum(r["interest"] for r in rs if r["payment"] > 0),
                      "build": sum(r["spend"] + r["draw"] for r in rs),
                      "cash": sum(r["net"] for r in rs), "balance": rs[-1]["balance"], "value": rs[-1]["value"],
                      "equity": rs[-1]["value"] - rs[-1]["balance"], "rate": rs[-1]["rate"]})
    reasons = []
    if irr is None or irr < d.hurdle:
        reasons.append("irr")
    if st["cash"] < 0:
        reasons.append("cash")
    if st["dscr"] is not None and st["dscr"] < d.dscr_min:
        reasons.append("dscr")
    open_m = d.build_months + d.lease_up_months + d.ramp_months
    after = rows[open_m:]
    worst = min(r["cash"] for r in after) if after else 0.0
    peak_out = 0.0
    c = 0.0
    for v in eq[:-1]:
        c += v
        peak_out = min(peak_out, c)
    return {
        "cost": cost, "cash_in": cash_in, "loan_used": loan, "ltv": loan / d.price if d.price else 0.0,
        "ltc": loan / cost if cost else 0.0, "stable": st,
        "yield_gross": d.rent * 12 / d.price if d.price else 0.0, "yield_on_cost": st["noi"] * 12 / cost if cost else 0.0,
        "cash_on_cash": st["cash"] * 12 / cash_in if cash_in > 0 else None,
        "irr": irr, "irr_unlevered": irr_monthly(un), "npv": npv,
        "multiple": (sum(c for c in eq[1:]) / cash_in) if cash_in > 0 else None,
        "profit": sum(eq), "payback_month": payback, "break_even_rent": be_rent, "break_even_occupancy": be_occ,
        "loan_max": loan_max, "worst_month_cash": worst, "peak_cash_out": -peak_out, "open_month": d.build_months + d.lease_up_months,
        "sale_net": sale_net, "split": split, "years": years, "passes": not reasons, "reasons": reasons,
    }


def stress(d: Deal) -> dict:
    """The same deal under three bad turns."""
    return {
        "rate_up_3": analyse(replace(d, float_rate=d.float_rate + 0.03)),
        "rent_down_20": analyse(replace(d, rent=d.rent * 0.8)),
        "no_price_growth": analyse(replace(d, price_growth=0.0)),
        "vacancy_25": analyse(replace(d, vacancy=0.25)),
    }
