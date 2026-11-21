"""Owned units: records (unit, lease, txn tables) and the per-unit and total financial summary.

Conventions (VND, ISO dates, rates annual fractions):

* ``unit.value`` / ``unit.loan`` / ``unit.cost`` describe the **whole property**; ``unit.share`` is the owner's
  fraction, applied to value, debt, cost and equity in :func:`summary`.
* ``txn.amount`` is the **owner's own cash** (+ in, − out), already their share — it is what hit their account.
* Debt is the annuity balance of ``loan`` at ``loan_rate`` over ``loan_term_years`` after the whole months elapsed
  since ``bought_at`` (a fixed-rate approximation; record actual principal payments as txns when they differ).
* Value is the latest ``valuation`` row for ``unit:<id>`` with ``as_of ≤ as_of``, else ``unit.value`` if its
  ``value_at`` is on or before ``as_of`` (or undated). No value → the unit's value fields are ``None`` with a reason.
* Trailing-12-month NOI = operating income (rent, other income) − operating costs over (as_of − 12 months, as_of];
  financing (loan_*), capital (purchase, sale, capex) and deposits (a liability) are excluded.
"""
from __future__ import annotations

import calendar
from datetime import date

from vnrealty.store.db import rows
from vnrealty.types import Insufficient

__all__ = ["CATEGORIES", "add_unit", "update_unit", "add_lease", "end_lease", "add_txn", "list_units", "rent_roll",
           "occupancy", "summary", "annuity_payment", "annuity_balance", "months_between", "add_months",
           "unit_value", "unit_debt", "NON_OPERATING"]

CATEGORIES = {"rent", "deposit", "repair", "tax", "fee", "utility", "loan_interest", "loan_principal", "purchase",
              "sale", "capex", "other"}
NON_OPERATING = {"deposit", "loan_interest", "loan_principal", "purchase", "sale", "capex"}
_UNIT_COLS = {"name", "ptype", "ward_code", "address", "lat", "lng", "area_m2", "bought_at", "cost", "share", "loan",
              "loan_rate", "loan_term_years", "value", "value_at", "legal", "status", "listing_id", "notes",
              "frontage_m", "depth_m", "alley_m", "road_width_m", "corner"}
_LEASE_COLS = {"tenant", "start", "end", "rent", "deposit", "due_day", "status", "notes"}


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def months_between(a: str, b: str) -> int:
    """Whole months from ISO date ``a`` to ``b`` (0 if b ≤ a)."""
    x, y = _d(a), _d(b)
    m = (y.year - x.year) * 12 + (y.month - x.month) - (1 if y.day < x.day else 0)
    return max(0, m)


def add_months(s: str, n: int) -> str:
    """ISO date ``s`` moved by ``n`` months (day clamped to the month's length)."""
    x = _d(s)
    t = x.year * 12 + x.month - 1 + n
    y, m = divmod(t, 12)
    m += 1
    return date(y, m, min(x.day, calendar.monthrange(y, m)[1])).isoformat()


def annuity_payment(principal: float, rate: float, term_years: float) -> float:
    """Monthly level payment (VND) repaying ``principal`` at ``rate`` over ``term_years``."""
    n = int(round(term_years * 12))
    if principal <= 0 or n <= 0:
        return 0.0
    r = rate / 12
    return principal / n if r == 0 else principal * r / (1 - (1 + r) ** -n)


def annuity_balance(principal: float, rate: float, term_years: float, months_paid: int) -> float:
    """Outstanding balance (VND) after ``months_paid`` level payments; 0 after the term."""
    n = int(round(term_years * 12))
    k = max(0, months_paid)
    if principal <= 0 or k >= n:
        return 0.0
    r = rate / 12
    if r == 0:
        return principal * (1 - k / n)
    return principal * ((1 + r) ** n - (1 + r) ** k) / ((1 + r) ** n - 1)


def add_unit(con, id: str, name: str, **fields) -> str:
    """Insert a unit; ``fields`` are unit columns (see store/db.py). Returns the id."""
    bad = set(fields) - _UNIT_COLS
    if bad:
        raise ValueError(f"unknown unit fields: {sorted(bad)}")
    cols = ["id", "name"] + list(fields)
    con.execute(f"INSERT INTO unit({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                [id, name] + list(fields.values()))
    con.commit()
    return id


def update_unit(con, id: str, **fields) -> None:
    """Update unit columns; raises KeyError if the unit does not exist."""
    bad = set(fields) - _UNIT_COLS
    if bad:
        raise ValueError(f"unknown unit fields: {sorted(bad)}")
    if not fields:
        return
    cur = con.execute(f"UPDATE unit SET {','.join(f'{k}=?' for k in fields)} WHERE id=?", [*fields.values(), id])
    if cur.rowcount == 0:
        raise KeyError(id)
    con.commit()


def add_lease(con, unit_id: str, start: str, rent: float, **fields) -> int:
    """Insert a lease (rent VND/month, deposit VND, due_day 1-31). Returns its id."""
    bad = set(fields) - _LEASE_COLS
    if bad:
        raise ValueError(f"unknown lease fields: {sorted(bad)}")
    cols = ["unit_id", "start", "rent"] + list(fields)
    cur = con.execute(f"INSERT INTO lease({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [unit_id, start, rent] + list(fields.values()))
    con.commit()
    return cur.lastrowid


def end_lease(con, lease_id: int, end: str, status: str = "ended") -> None:
    """Set a lease's end date and status."""
    cur = con.execute("UPDATE lease SET end=?, status=? WHERE id=?", (end, status, lease_id))
    if cur.rowcount == 0:
        raise KeyError(lease_id)
    con.commit()


def add_txn(con, at: str, amount: float, category: str, unit_id: str | None = None, lease_id: int | None = None,
            period: str | None = None, memo: str | None = None) -> int:
    """Record money in (+) or out (−), VND. ``period`` is 'YYYY-MM' for rent. Returns the id."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; known: {sorted(CATEGORIES)}")
    cur = con.execute("INSERT INTO txn(unit_id, lease_id, at, amount, category, period, memo) VALUES (?,?,?,?,?,?,?)",
                      (unit_id, lease_id, at, amount, category, period, memo))
    con.commit()
    return cur.lastrowid


def list_units(con, status: str | None = None) -> list[dict]:
    """All units (optionally filtered by status), by id."""
    if status:
        return rows(con, "SELECT * FROM unit WHERE status=? ORDER BY id", (status,))
    return rows(con, "SELECT * FROM unit ORDER BY id")


def rent_roll(con, as_of: str) -> list[dict]:
    """Leases running on ``as_of``: start ≤ as_of, no end or end ≥ as_of, status 'active'. Rent VND/month."""
    return rows(con, """SELECT l.id AS lease_id, l.unit_id, u.name AS unit_name, l.tenant, l.start, l.end, l.rent,
                               l.deposit, l.due_day FROM lease l JOIN unit u ON u.id = l.unit_id
                        WHERE l.status = 'active' AND l.start <= ? AND (l.end IS NULL OR l.end >= ?)
                        ORDER BY l.unit_id, l.start""", (as_of[:10], as_of[:10]))


def occupancy(con, as_of: str) -> dict:
    """Held units with a running lease on ``as_of``: count, total, rate (None when no units are held)."""
    held = [u["id"] for u in list_units(con, "held")]
    let = {r["unit_id"] for r in rent_roll(con, as_of)}
    n = sum(1 for u in held if u in let)
    return {"let": n, "held": len(held), "rate": n / len(held) if held else None,
            "vacant": [u for u in held if u not in let]}


def unit_value(con, u: dict, as_of: str) -> dict | Insufficient:
    """Latest value (VND, whole property) known on ``as_of`` and where it came from."""
    v = rows(con, "SELECT value, as_of, method FROM valuation WHERE subject=? AND as_of<=? AND value IS NOT NULL "
                  "ORDER BY as_of DESC, id DESC LIMIT 1", (f"unit:{u['id']}", as_of))
    if v:
        return {"value": v[0]["value"], "at": v[0]["as_of"], "source": f"valuation:{v[0]['method']}"}
    if u.get("value") is not None and (not u.get("value_at") or u["value_at"][:10] <= as_of[:10]):
        return {"value": u["value"], "at": u.get("value_at"), "source": "unit.value"}
    return Insufficient("unit_value", f"no value for unit {u['id']} on or before {as_of}")


def unit_debt(u: dict, as_of: str) -> dict | Insufficient:
    """Outstanding loan (VND, whole property) on ``as_of`` and its scheduled monthly payment."""
    loan = u.get("loan") or 0.0
    if loan <= 0:
        return {"balance": 0.0, "payment": 0.0, "months_paid": 0, "remaining_months": 0}
    miss = [k for k in ("loan_rate", "loan_term_years", "bought_at") if u.get(k) is None]
    if miss:
        return Insufficient("unit_debt", f"unit {u['id']} has a loan but no " + ", ".join(miss))
    k = months_between(u["bought_at"], as_of)
    n = int(round(u["loan_term_years"] * 12))
    bal = annuity_balance(loan, u["loan_rate"], u["loan_term_years"], k)
    return {"balance": bal, "payment": annuity_payment(loan, u["loan_rate"], u["loan_term_years"]) if k < n else 0.0,
            "months_paid": k, "remaining_months": max(0, n - k)}


def _ttm(con, unit_id: str, as_of: str) -> dict:
    lo = add_months(as_of, -12)
    by: dict[str, float] = {}
    for r in rows(con, "SELECT category, SUM(amount) AS s FROM txn WHERE unit_id=? AND at>? AND at<=? GROUP BY category",
                  (unit_id, lo, as_of[:10] + "T99")):
        by[r["category"]] = r["s"]
    op = {k: v for k, v in by.items() if k not in NON_OPERATING}
    return {"by_category": by, "rent": by.get("rent", 0.0), "noi": sum(op.values()),
            "opex": -sum(v for v in op.values() if v < 0),
            "debt_service": -(by.get("loan_interest", 0.0) + by.get("loan_principal", 0.0))}


def summary(con, as_of: str) -> dict:
    """Per held unit and in total: value, debt, equity (× share), trailing-12m NOI, debt service paid, yield on value
    and on cost, cash-on-cash ((NOI − debt service) / (cost − loan) × share). A unit whose value or debt cannot be
    established shows ``None`` there and an entry in ``gaps``; it is left out of the totals that need it."""
    out, gaps = [], []
    tot = {"value": 0.0, "debt": 0.0, "equity": 0.0, "noi_ttm": 0.0, "debt_service_ttm": 0.0, "cost": 0.0,
           "own_cash": 0.0, "monthly_payment": 0.0}
    for u in list_units(con, "held"):
        sh = u["share"] if u["share"] is not None else 1.0
        v = unit_value(con, u, as_of)
        dbt = unit_debt(u, as_of)
        t = _ttm(con, u["id"], as_of)
        val = None if isinstance(v, Insufficient) else v["value"] * sh
        debt = None if isinstance(dbt, Insufficient) else dbt["balance"] * sh
        for g in (v, dbt):
            if isinstance(g, Insufficient):
                gaps.append({"unit": u["id"], "method": g.method, "reason": g.reason})
        cost = u["cost"] * sh if u["cost"] else None
        own = (u["cost"] - (u["loan"] or 0.0)) * sh if u["cost"] else None
        row = {"id": u["id"], "name": u["name"], "ptype": u["ptype"], "ward_code": u["ward_code"], "share": sh,
               "legal": u["legal"], "value": val, "value_source": None if val is None else v["source"],
               "debt": debt, "monthly_payment": None if debt is None else dbt["payment"] * sh,
               "equity": val - debt if val is not None and debt is not None else None,
               "ltv": debt / val if val and debt is not None else None,
               "noi_ttm": t["noi"], "rent_ttm": t["rent"], "opex_ttm": t["opex"], "debt_service_ttm": t["debt_service"],
               "yield_on_value": t["noi"] / val if val else None, "yield_on_cost": t["noi"] / cost if cost else None,
               "cash_on_cash": (t["noi"] - t["debt_service"]) / own if own and own > 0 else None,
               "cost": cost, "notes": u["notes"]}
        out.append(row)
        tot["noi_ttm"] += t["noi"]
        tot["debt_service_ttm"] += t["debt_service"]
        if val is not None:
            tot["value"] += val
        if debt is not None:
            tot["debt"] += debt
            tot["monthly_payment"] += row["monthly_payment"]
        if row["equity"] is not None:
            tot["equity"] += row["equity"]
        if cost:
            tot["cost"] += cost
        if own:
            tot["own_cash"] += own
    tot["yield_on_value"] = tot["noi_ttm"] / tot["value"] if tot["value"] else None
    tot["yield_on_cost"] = tot["noi_ttm"] / tot["cost"] if tot["cost"] else None
    tot["cash_on_cash"] = ((tot["noi_ttm"] - tot["debt_service_ttm"]) / tot["own_cash"]) if tot["own_cash"] > 0 else None
    tot["ltv"] = tot["debt"] / tot["value"] if tot["value"] else None
    tot["complete"] = not gaps
    return {"as_of": as_of, "units": out, "total": tot, "gaps": gaps}
