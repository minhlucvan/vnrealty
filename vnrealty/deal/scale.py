"""Portfolio ladder: grow a real-estate business by repeating one deal (deal.engine) as the unit.

Python port of web/scale.js, line for line, so the browser page and the CLI give the same answer
(web/check_parity.py compares them). Month by month:

1. each owned unit pays its month's equity cash flow (NOI − mortgage − own build money), and any cash-out
   refinance loan takes its payment;
2. savings come in; property managers are paid once the book outgrows self-management;
3. a refinance fires on a unit when it reaches ``refi_years``: new debt up to ``refi_ltv`` of today's value;
4. one new unit is bought when ALL hold: units < max_units, the unit earns a positive NOI, cash after its peak
   equity need still covers ``reserve_months`` of the whole book's debt service, its DSCR clears the floor, and
   portfolio LTV after the purchase stays at or under ``ltv_cap``.

A unit bought later costs more: price-type fields move with price_growth, rent with rent_growth, costs with
cost_growth, and the loan keeps the same share of the price — cut to the DSCR maximum when that is lower, as a
bank would size it. Stdlib only.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace

from .engine import Deal, _pay, _schedule, analyse

__all__ = ["Scale", "scale_run", "scale_unit"]


@dataclass(frozen=True)
class Scale:
    cash0: float = 2e9
    save_month: float = 20e6
    horizon_years: float = 15
    max_units: int = 8
    reserve_months: float = 6
    refi_years: float = 5
    refi_ltv: float = 0.5
    refi_cost: float = 0.01
    ltv_cap: float = 0.6
    mgr_every: int = 4
    mgr_cost: float = 12e6
    target_month: float = 50e6
    last_buy_years: float = 2


def scale_unit(d: Deal, t: int) -> Deal:
    gp, gr, gc = ((1 + g) ** (t / 12) for g in (d.price_growth, d.rent_growth, d.cost_growth))
    return replace(d, price=d.price * gp, value_after=d.value_after * gp, renovation=d.renovation * gc, build_cost=d.build_cost * gc,
                   loan=d.loan * gp, rent=d.rent * gr, running_costs=d.running_costs * gc, staff=d.staff * gc)


def scale_run(d: Deal, s: Scale = Scale()) -> dict:
    H = round(s.horizon_years * 12)
    last_buy = H - round(s.last_buy_years * 12)
    units: list[dict] = []
    buys: list[dict] = []
    months: list[dict] = []
    blocked: dict[str, int] = {}
    cash, target_month = s.cash0, None

    def managers(n: int) -> int:
        return max(0, math.ceil(n / s.mgr_every) - 1) if s.mgr_every > 0 else 0

    for t in range(H + 1):
        noi = ds = flow = value = debt = refi_in = 0.0
        for u in units:
            k = t - u["month"]
            r = u["rows"][k]
            if k >= 1:
                flow += r["net"]; noi += r["noi"]; ds += r["payment"]
                if u["refi"] > 0:
                    i = u["refi"] * u["refi_rate"] / 12
                    p = min(u["refi_pay"], u["refi"] + i)
                    u["refi"] = max(0.0, u["refi"] - (p - i)); flow -= p; ds += p
            if s.refi_years > 0 and k == round(s.refi_years * 12) and k >= u["open_m"]:
                room = r["value"] * s.refi_ltv - r["balance"] - u["refi"]
                if room > 0:
                    u["refi"] += room
                    u["refi_rate"] = u["d"].float_rate
                    u["refi_pay"] = _pay(u["refi"], u["refi_rate"], u["d"].term_years * 12)
                    refi_in += room * (1 - s.refi_cost)
            value += r["value"]; debt += r["balance"] + u["refi"]
        overhead = managers(len(units)) * s.mgr_cost * (1 + d.cost_growth) ** (t / 12) if t >= 1 else 0.0
        save = s.save_month if t >= 1 else 0.0
        cash += flow + save - overhead + refi_in
        op_cash = noi - ds - overhead
        if target_month is None and t >= 1 and units and op_cash >= s.target_month:
            target_month = t
        bought = None
        if len(units) < s.max_units and t <= last_buy:
            ud = scale_unit(d, t)
            a = analyse(ud)
            if a["loan_max"] is not None and ud.loan > a["loan_max"]:
                ud = replace(ud, loan=a["loan_max"]); a = analyse(ud)
            rows = _schedule(replace(ud, hold_years=max(1, math.ceil((H - t) / 12))))
            st = a["stable"]
            reserve = s.reserve_months * (ds + st["debt_service"])
            uval = rows[0].get("value") or (ud.value_after + ud.build_cost)
            ltv_after = (debt + a["loan_used"]) / (value + ud.value_after + ud.build_cost)
            why = ("noi" if st["noi"] <= 0 else "cash" if cash - a["peak_cash_out"] < reserve
                   else "dscr" if st["dscr"] is not None and st["dscr"] < ud.dscr_min - 1e-9
                   else "ltv" if ltv_after > s.ltv_cap + 1e-9 else None)
            if why:
                blocked[why] = blocked.get(why, 0) + 1
            else:
                cash -= rows[0]["spend"]
                units.append({"month": t, "d": ud, "rows": rows, "refi": 0.0, "refi_rate": 0.0, "refi_pay": 0.0,
                              "open_m": ud.build_months + ud.lease_up_months})
                bought = {"month": t, "price": ud.price, "cost": a["cost"], "loan": a["loan_used"], "need": a["peak_cash_out"],
                          "cash_after": cash, "dscr": st["dscr"], "irr": a["irr"]}
                buys.append(bought); value += uval; debt += rows[0]["balance"]
        months.append({"month": t, "units": len(units), "value": value, "debt": debt, "cash": cash, "noi": noi, "debt_service": ds,
                       "overhead": overhead, "op_cash": op_cash, "refi_in": refi_in, "equity": value - debt + cash,
                       "ltv": debt / value if value > 0 else 0.0, "dscr": noi / ds if ds > 0 else None,
                       "managers": managers(len(units)), "bought": bought})
    e = months[H]
    sell_net = sum(u["rows"][H - u["month"]]["value"] * (1 - u["d"].sell_costs) - u["rows"][H - u["month"]]["balance"] - u["refi"] for u in units)
    years = []
    for y in range(1, int(s.horizon_years) + 1):
        ms = months[(y - 1) * 12 + 1: y * 12 + 1]
        m = ms[-1]
        years.append({"year": y, "units": m["units"], "value": m["value"], "debt": m["debt"], "cash": m["cash"], "equity": m["equity"],
                      "ltv": m["ltv"], "noi": sum(x["noi"] for x in ms), "debt_service": sum(x["debt_service"] for x in ms),
                      "overhead": sum(x["overhead"] for x in ms), "op_cash": sum(x["op_cash"] for x in ms), "refi_in": sum(x["refi_in"] for x in ms),
                      "bought": sum(1 for x in ms if x["bought"]) + (1 if y == 1 and months[0]["bought"] else 0), "managers": m["managers"]})
    return {"buys": buys, "months": months, "years": years, "blocked": blocked, "target_month": target_month, "horizon_months": H,
            "settings": asdict(s),
            "end": {"units": e["units"], "value": e["value"], "debt": e["debt"], "cash": e["cash"], "equity": e["equity"],
                    "net_worth": e["cash"] + sell_net, "monthly_cash": e["op_cash"], "ltv": e["ltv"], "dscr": e["dscr"], "managers": e["managers"]}}
