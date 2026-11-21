"""Month-end close for the units we operate: who paid, who is late, what was spent, what needs attention.

``monthly_close(con, 'YYYY-MM', as_of=None)``:

* **Expected rent** — every lease with status 'active' or 'ended' whose term covers the month's due date
  (``due_day``, clamped to the month's length) owes one full month's ``rent`` (VND; no proration — record a
  part-month as its own txn and lease).
* **Received** — ``rent`` txns for that lease with ``period`` = the month, or, when ``period`` is empty, dated in
  the month. Status: ``paid`` (received ≥ expected), ``partial``, ``overdue`` (nothing received and the due date
  has passed on ``as_of``) or ``due`` (not yet due). ``days_late``: for paid, the date the rent was completed minus
  the due date (≥ 0); for unpaid or partial past the due date, ``as_of`` minus the due date.
* **Expenses by category** — negative txns dated in the month; **net cash** — the sum of every txn in the month.
* **Renewals** — running leases ending within 60 days after ``as_of``; **deposits held** — Σ deposit of running
  leases.
* **Alerts** — overdue and partial rents, renewals, held units with no lease, negative net cash.

``as_of`` defaults to the last day of the month.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from vnrealty.store.db import rows

from .units import list_units, rent_roll

__all__ = ["monthly_close", "RENEWAL_WINDOW_DAYS"]

RENEWAL_WINDOW_DAYS = 60


def _bounds(month: str) -> tuple[date, date]:
    y, m = int(month[:4]), int(month[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def monthly_close(con, month: str, as_of: str | None = None) -> dict:
    """Close ``month`` ('YYYY-MM') as seen on ``as_of`` (ISO date; default the month's last day). VND."""
    first, last = _bounds(month)
    asof = date.fromisoformat(as_of[:10]) if as_of else last
    leases = rows(con, "SELECT l.*, u.name AS unit_name FROM lease l JOIN unit u ON u.id=l.unit_id "
                       "WHERE l.status IN ('active','ended') ORDER BY l.unit_id, l.id")
    rent_lines, alerts = [], []
    for L in leases:
        dd = min(max(1, L["due_day"] or 5), last.day)
        due = date(first.year, first.month, dd)
        start = date.fromisoformat(L["start"][:10])
        end = date.fromisoformat(L["end"][:10]) if L["end"] else None
        if start > due or (end is not None and end < due):
            continue
        pays = rows(con, "SELECT at, amount FROM txn WHERE lease_id=? AND category='rent' AND "
                         "(period=? OR (period IS NULL AND substr(at,1,7)=?)) AND substr(at,1,10)<=? ORDER BY at, id",
                    (L["id"], month, month, asof.isoformat()))
        exp, got, done_at = L["rent"], 0.0, None
        for p in pays:
            got += p["amount"]
            if done_at is None and got >= exp - 0.5:
                done_at = date.fromisoformat(p["at"][:10])
        if done_at is not None:
            status, late = "paid", max(0, (done_at - due).days)
        elif asof > due:
            status, late = ("partial" if got > 0 else "overdue"), (asof - due).days
        else:
            status, late = ("partial" if got > 0 else "due"), 0
        line = {"lease_id": L["id"], "unit_id": L["unit_id"], "unit_name": L["unit_name"], "tenant": L["tenant"],
                "due_date": due.isoformat(), "expected": exp, "received": got, "outstanding": max(0.0, exp - got),
                "status": status, "days_late": late}
        rent_lines.append(line)
        if status in ("overdue", "partial") and asof > due:
            alerts.append({"kind": f"rent_{status}", "unit_id": L["unit_id"], "lease_id": L["id"],
                           "amount": line["outstanding"], "days_late": late,
                           "detail": f"{L['unit_name']}: {line['outstanding']:,.0f} VND outstanding, {late} days late"})
    month_txns = rows(con, "SELECT category, amount FROM txn WHERE substr(at,1,7)=? AND substr(at,1,10)<=?",
                      (month, asof.isoformat()))
    expenses: dict[str, float] = {}
    for t in month_txns:
        if t["amount"] < 0:
            expenses[t["category"]] = expenses.get(t["category"], 0.0) + t["amount"]
    net = sum(t["amount"] for t in month_txns)
    running = rent_roll(con, asof.isoformat())
    horizon = asof + timedelta(days=RENEWAL_WINDOW_DAYS)
    renewals = [{"lease_id": r["lease_id"], "unit_id": r["unit_id"], "tenant": r["tenant"], "end": r["end"],
                 "days_left": (date.fromisoformat(r["end"][:10]) - asof).days}
                for r in running if r["end"] and asof <= date.fromisoformat(r["end"][:10]) <= horizon]
    for r in renewals:
        alerts.append({"kind": "renewal_due", "unit_id": r["unit_id"], "lease_id": r["lease_id"],
                       "days_left": r["days_left"], "detail": f"lease {r['lease_id']} ends {r['end']} ({r['days_left']} days)"})
    let = {r["unit_id"] for r in running}
    for u in list_units(con, "held"):
        if u["id"] not in let:
            alerts.append({"kind": "vacant", "unit_id": u["id"], "detail": f"{u['name']} has no running lease"})
    if net < 0:
        alerts.append({"kind": "negative_net_cash", "amount": net, "detail": f"net cash for {month} is {net:,.0f} VND"})
    exp_total = sum(l["expected"] for l in rent_lines)
    rec_total = sum(l["received"] for l in rent_lines)
    return {"month": month, "as_of": asof.isoformat(), "rent": rent_lines, "expected_rent": exp_total,
            "received_rent": rec_total, "collection_rate": rec_total / exp_total if exp_total else None,
            "expenses": expenses, "expenses_total": sum(expenses.values()), "net_cash": net,
            "renewals": renewals, "deposits_held": sum(r["deposit"] or 0.0 for r in running), "alerts": alerts}
