"""Portfolio risk: concentration, leverage, coverage, liquidity, shocks and flags — each flag with its number.

Built on :func:`vnrealty.portfolio.units.summary` (values and debts are the owner's share; NOI and debt service are
trailing-12-month txns). Definitions (VND, months, fractions):

* **Concentration** — weights are each held unit's value share; HHI = Σ wᵢ² over groups (1 = everything in one
  ward / type), top share = the largest group's weight. Units without a value are excluded and listed in gaps.
* **LTV** = Σ debt / Σ value.  **DSCR** = NOI ttm / annual scheduled debt service (12 × the annuity payment of
  each loan). ``None`` without debt.
* **Liquidity months** = ``cash`` / (monthly scheduled debt service + monthly fixed costs); fixed costs default to
  operating costs ttm / 12 (pass ``fixed_costs_month`` to override).
* **Shocks** — rates +2 and +3 points: each loan's payment recomputed on its current balance over its remaining
  term; prices −20% and −30%: LTV after; vacancy +20 points: NOI ttm minus 20% of rent ttm. Override the shock
  sizes with ``stress={'rate_up': [...], 'price_down': [...], 'vacancy_up': [...]}``.
* **Flags** (code, severity, value, threshold): legal title not ``so_hong``/``so_do`` (high), portfolio LTV >
  ``ltv_limit`` (high), DSCR < ``dscr_min`` (high), liquidity < ``liquidity_min`` months (medium), a unit LTV above
  the limit (medium), shocked DSCR < 1 or shocked LTV > the limit (medium), adverse zoning (high), missing value or
  debt (medium).

**Zoning convention.** ``unit.notes`` may carry tokens ``zoning:<code>`` (e.g. ``zoning:road_widening``,
``zoning:clearance``, ``zoning:green_space``, ``zoning:setback``). Any ``zoning:`` token flags the unit except
``zoning:ok`` and ``zoning:clear``. Write the token when the ward's quy hoạch information sheet shows the plot
affected; the token is the record that the check found something.
"""
from __future__ import annotations

import re

from .units import annuity_payment, list_units, summary, unit_debt

__all__ = ["risk_report", "hhi", "zoning_flags", "GOOD_TITLES", "DEFAULT_STRESS"]

GOOD_TITLES = {"so_hong", "so_do"}
DEFAULT_STRESS = {"rate_up": [0.02, 0.03], "price_down": [0.20, 0.30], "vacancy_up": [0.20]}
_ZONING = re.compile(r"zoning:([A-Za-z0-9_\-]+)")


def hhi(weights: dict[str, float]) -> dict:
    """Herfindahl index and top group of non-negative ``weights`` (normalised here)."""
    t = sum(weights.values())
    if t <= 0:
        return {"hhi": None, "top": None, "top_share": None, "shares": {}}
    sh = {k: v / t for k, v in weights.items()}
    top = max(sh, key=sh.get)
    return {"hhi": sum(s * s for s in sh.values()), "top": top, "top_share": sh[top], "shares": sh}


def zoning_flags(notes: str | None) -> list[str]:
    """Adverse zoning codes in a unit's notes (see the module's convention)."""
    return [c for c in _ZONING.findall(notes or "") if c.lower() not in ("ok", "clear")]


def _dscr(noi: float, ds_year: float) -> float | None:
    return noi / ds_year if ds_year > 0 else None


def risk_report(con, as_of: str, cash: float, stress: dict | None = None, ltv_limit: float = 0.6,
                dscr_min: float = 1.2, liquidity_min: float = 6.0, fixed_costs_month: float | None = None) -> dict:
    """The portfolio's risk on ``as_of`` with ``cash`` (VND) on hand. See the module docstring for every formula."""
    st = {**DEFAULT_STRESS, **(stress or {})}
    s = summary(con, as_of)
    units = s["units"]
    raw = {u["id"]: u for u in list_units(con, "held")}
    flags: list[dict] = []
    for g in s["gaps"]:
        flags.append({"code": "data_gap", "severity": "medium", "unit": g["unit"], "value": None, "threshold": None,
                      "detail": g["reason"]})
    valued = [u for u in units if u["value"]]
    by_ward: dict[str, float] = {}
    by_ptype: dict[str, float] = {}
    for u in valued:
        by_ward[u["ward_code"] or "unknown"] = by_ward.get(u["ward_code"] or "unknown", 0.0) + u["value"]
        by_ptype[u["ptype"] or "unknown"] = by_ptype.get(u["ptype"] or "unknown", 0.0) + u["value"]
    value = sum(u["value"] for u in valued)
    debt = sum(u["debt"] for u in units if u["debt"] is not None)
    ltv = debt / value if value else None
    pay_m = sum(u["monthly_payment"] for u in units if u["monthly_payment"] is not None)
    noi = s["total"]["noi_ttm"]
    rent = sum(u["rent_ttm"] for u in units)
    opex_m = sum(u["opex_ttm"] for u in units) / 12 if fixed_costs_month is None else fixed_costs_month
    dscr = _dscr(noi, 12 * pay_m)
    outgo = pay_m + opex_m
    liq = cash / outgo if outgo > 0 else None

    rate_shocks = []
    for dr in st["rate_up"]:
        p = 0.0
        for u in units:
            r = raw[u["id"]]
            d = unit_debt(r, as_of)
            if isinstance(d, dict) and d["balance"] > 0 and d["remaining_months"] > 0:
                p += annuity_payment(d["balance"], r["loan_rate"] + dr, d["remaining_months"] / 12) * u["share"]
        ds = _dscr(noi, 12 * p)
        rate_shocks.append({"rate_up": dr, "monthly_payment": p, "dscr": ds,
                            "liquidity_months": cash / (p + opex_m) if p + opex_m > 0 else None})
    price_shocks = [{"price_down": dp, "ltv": debt / (value * (1 - dp)) if value and dp < 1 else None}
                    for dp in st["price_down"]]
    vac_shocks = [{"vacancy_up": dv, "noi": noi - dv * rent, "dscr": _dscr(noi - dv * rent, 12 * pay_m)}
                  for dv in st["vacancy_up"]]

    for u in units:
        if (u["legal"] or "unknown") not in GOOD_TITLES:
            flags.append({"code": "legal_title", "severity": "high", "unit": u["id"], "value": u["legal"],
                          "threshold": sorted(GOOD_TITLES), "detail": f"{u['name']}: title '{u['legal']}' is not a sổ hồng/sổ đỏ"})
        if u["ltv"] is not None and u["ltv"] > ltv_limit:
            flags.append({"code": "unit_ltv", "severity": "medium", "unit": u["id"], "value": u["ltv"], "threshold": ltv_limit,
                          "detail": f"{u['name']}: LTV {u['ltv']:.0%} above {ltv_limit:.0%}"})
        for z in zoning_flags(u["notes"]):
            flags.append({"code": "zoning", "severity": "high", "unit": u["id"], "value": z, "threshold": None,
                          "detail": f"{u['name']}: planning flag '{z}'"})
    if ltv is not None and ltv > ltv_limit:
        flags.append({"code": "ltv", "severity": "high", "unit": None, "value": ltv, "threshold": ltv_limit,
                      "detail": f"portfolio LTV {ltv:.0%} above {ltv_limit:.0%}"})
    if dscr is not None and dscr < dscr_min:
        flags.append({"code": "dscr", "severity": "high", "unit": None, "value": dscr, "threshold": dscr_min,
                      "detail": f"DSCR {dscr:.2f} below {dscr_min}"})
    if liq is not None and liq < liquidity_min:
        flags.append({"code": "liquidity", "severity": "medium", "unit": None, "value": liq, "threshold": liquidity_min,
                      "detail": f"cash covers {liq:.1f} months of debt service and fixed costs (< {liquidity_min})"})
    for r in rate_shocks:
        if r["dscr"] is not None and r["dscr"] < 1.0:
            flags.append({"code": "rate_shock", "severity": "medium", "unit": None, "value": r["dscr"], "threshold": 1.0,
                          "detail": f"rates +{r['rate_up'] * 100:.0f} pts: DSCR {r['dscr']:.2f} < 1"})
    for r in price_shocks:
        if r["ltv"] is not None and r["ltv"] > ltv_limit:
            flags.append({"code": "price_shock", "severity": "medium", "unit": None, "value": r["ltv"], "threshold": ltv_limit,
                          "detail": f"prices −{r['price_down']:.0%}: LTV {r['ltv']:.0%} above {ltv_limit:.0%}"})
    for r in vac_shocks:
        if r["dscr"] is not None and r["dscr"] < 1.0:
            flags.append({"code": "vacancy_shock", "severity": "medium", "unit": None, "value": r["dscr"], "threshold": 1.0,
                          "detail": f"vacancy +{r['vacancy_up'] * 100:.0f} pts: DSCR {r['dscr']:.2f} < 1"})
    return {
        "as_of": as_of, "cash": cash, "value": value, "debt": debt, "ltv": ltv, "noi_ttm": noi,
        "monthly_debt_service": pay_m, "monthly_fixed_costs": opex_m, "dscr": dscr, "liquidity_months": liq,
        "concentration": {"ward": hhi(by_ward), "ptype": hhi(by_ptype)},
        "shocks": {"rates": rate_shocks, "prices": price_shocks, "vacancy": vac_shocks},
        "flags": flags, "gaps": s["gaps"], "limits": {"ltv": ltv_limit, "dscr": dscr_min, "liquidity_months": liquidity_min},
    }
