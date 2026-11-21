"""Everything about one owned unit, in one payload: the input to `vnr report asset <id>`.

From the database:
- the unit row;
- its transactions, leases and journal entries;
- every valuation recorded for it (its value history);
- legal checklist status.

From the caller, already computed by the libraries:
- today's triangulated value;
- the plan evaluation and its what-if sensitivities;
- the price projection.

From an optional private asset document (``data/portfolio/<id>.json``): timeline, actions, documents, images,
funding, known gaps. These are owner records the database does not model.

The only arithmetic done here is per-unit position maths on library outputs:
- your share of the value;
- what you paid (purchase transactions, else cost × share);
- the gain, and the annualised return on what you paid;
- equity after the unit's own debt.

Money is VND. Nothing here writes to the database.
"""
from __future__ import annotations

import datetime as _dt
import json
import sqlite3

from vnrealty.types import Estimate, Insufficient

__all__ = ["assemble", "position", "value_history"]


def _rows(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def value_history(con: sqlite3.Connection, unit_id: str, as_of: str) -> list[dict]:
    """Recorded valuations of ``unit:<id>`` with as_of <= ``as_of``, oldest first: {as_of, method, value, lo, hi, n}."""
    return _rows(con, "SELECT as_of, method, value, lo, hi, n FROM valuation WHERE subject = ? AND as_of <= ? "
                      "ORDER BY as_of, id", (f"unit:{unit_id}", as_of))


def _years_between(a: str | None, b: str) -> float | None:
    try:
        d0 = _dt.date.fromisoformat(str(a)[:10])
        d1 = _dt.date.fromisoformat(str(b)[:10])
    except (TypeError, ValueError):
        return None
    y = (d1 - d0).days / 365.25
    return y if y > 0 else None


def position(unit: dict, txns: list[dict], value: float | None, debt: float | None, as_of: str) -> dict:
    """Your position in the unit.

    Returns:
    - ``own_value`` = value × share;
    - ``paid``: the sum of −purchase/capex transactions, else cost × share;
    - ``gain`` = own_value − paid;
    - ``gain_pct``;
    - ``cagr``: annualised from bought_at to as_of;
    - ``equity`` = own_value − debt;
    - ``price_m2`` = value ÷ area.

    Any input that is missing makes its outputs None, never zero.
    """
    share = unit.get("share") if unit.get("share") is not None else 1.0
    paid_tx = -sum(t["amount"] for t in txns if t.get("category") in ("purchase", "capex") and t.get("amount") is not None)
    paid = paid_tx if paid_tx > 0 else (unit["cost"] * share if unit.get("cost") else None)
    own = value * share if value is not None else None
    gain = own - paid if own is not None and paid else None
    yrs = _years_between(unit.get("bought_at"), as_of)
    cagr = (own / paid) ** (1 / yrs) - 1 if own and paid and yrs and own > 0 else None
    area = unit.get("area_m2")
    return {"share": share, "own_value": own, "paid": paid, "paid_basis": "transactions" if paid_tx > 0 else "cost × share",
            "gain": gain, "gain_pct": gain / paid if gain is not None and paid else None, "years_held": yrs, "cagr": cagr,
            "debt": debt, "equity": own - debt if own is not None and debt is not None else None,
            "price_m2": value / area if value is not None and area else None}


def _value_parts(value: dict | None) -> tuple[float | None, float | None, float | None, list[dict]]:
    """(value, lo, hi, methods) from a `run_value` result (``combined`` + ``methods``), tolerating Insufficient."""
    if not value:
        return None, None, None, []
    comb = value.get("combined")
    methods = []
    for name, m in (value.get("methods") or {}).items():
        if isinstance(m, Estimate):
            methods.append({"method": name, "status": "ok", "value": m.value, "lo": m.lo, "hi": m.hi, "n": m.n})
        elif isinstance(m, Insufficient):
            methods.append({"method": name, "status": "insufficient", "reason": m.reason})
        elif isinstance(m, dict):
            methods.append({"method": name, **m})
    if isinstance(comb, Estimate):
        return comb.value, comb.lo, comb.hi, methods
    if isinstance(comb, dict) and comb.get("value") is not None:
        return comb["value"], comb.get("lo"), comb.get("hi"), methods
    return None, None, None, methods


def assemble(con: sqlite3.Connection, unit_id: str, as_of: str, *, value: dict | None = None, plan: dict | None = None,
             sensitivities: list[dict] | None = None, projection: dict | None = None, doc: dict | None = None,
             debt: float | None = None, legal: dict | None = None, projects: list[dict] | None = None) -> dict | Insufficient:
    """The asset payload. ``value`` is a `run_value` result; ``plan`` an options.evaluate result; ``sensitivities``
    [{name, overrides, best, irr}]; ``projection`` the `vnr project` result; ``doc`` the private asset document."""
    u = con.execute("SELECT * FROM unit WHERE id = ?", (unit_id,)).fetchone()
    if u is None:
        return Insufficient("asset", f"no unit {unit_id}")
    unit = dict(u)
    txns = _rows(con, "SELECT at, amount, category, period, memo FROM txn WHERE unit_id = ? AND at <= ? ORDER BY at, id",
                 (unit_id, as_of))
    leases = _rows(con, "SELECT tenant, start, end, rent, deposit, status FROM lease WHERE unit_id = ? ORDER BY start", (unit_id,))
    journal = _rows(con, "SELECT at, kind, body FROM journal WHERE subject = ? ORDER BY at, id", (f"unit:{unit_id}",))
    v, lo, hi, methods = _value_parts(value)
    doc = doc or {}
    return {
        "unit": unit, "as_of": as_of, "value": v, "lo": lo, "hi": hi, "methods": methods,
        "position": position(unit, txns, v, debt, as_of),
        "value_history": value_history(con, unit_id, as_of),
        "txns": txns or [dict(t, source="asset document") for t in doc.get("txns", [])],
        "txns_source": "database" if txns else ("asset document" if doc.get("txns") else None),
        "leases": leases, "journal": journal, "legal": legal, "plan": plan, "sensitivities": sensitivities or [],
        "projection": projection, "projects": projects or [],
        "timeline": doc.get("timeline", []), "actions": doc.get("actions", []), "documents": doc.get("documents", []),
        "images": doc.get("images") or {}, "funding": doc.get("funding", []), "gaps": doc.get("gaps", []),
        "doc_loaded": bool(doc),
    }


def load_doc(path) -> dict:
    """The private asset document, or {} when absent. Never fabricates fields."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
