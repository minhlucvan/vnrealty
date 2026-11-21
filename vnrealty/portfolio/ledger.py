"""Paper deals: every buy / pass / sell / hold / build decision recorded with its reasoning, then graded.

A decision goes into the ``deal`` table when it is made (``open_paper_deal``) with the price faced, the value we
estimated, the spec (inputs, JSON) and the verdict text. When the truth arrives — a sale nearby, our own sale, a
valuation a year on — ``close`` records the outcome as JSON, which must carry ``realised_value`` (VND) to be graded.

:func:`scorecard` grades closed deals:

* **hit** — the realised value fell on the side of the price the decision bet on: for ``buy``/``build``/``hold``,
  realised ≥ price; for ``pass``/``sell``, realised < price;
* **estimated gap** = (est_value − price) / price; **realised gap** = (realised_value − price) / price;
* **estimate error** = realised_value / est_value − 1 (how far our value was off).

Closed deals without a ``realised_value`` (or without a price) are counted as ``ungraded``, never as misses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from vnrealty.store.db import dumps, rows

__all__ = ["ACTIONS", "open_paper_deal", "close", "list_deals", "scorecard"]

ACTIONS = {"buy", "pass", "sell", "hold", "build"}
_LONG = {"buy", "build", "hold"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_paper_deal(con, subject: str, action: str, price: float | None, est_value: float | None,
                    spec: dict | None = None, verdict: str | None = None, opened_at: str | None = None) -> int:
    """Record a decision on ``subject`` ('listing:<id>', 'lot:<name>', ...). Prices VND. Returns the deal id."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; known: {sorted(ACTIONS)}")
    cur = con.execute("INSERT INTO deal(subject, opened_at, action, price, est_value, spec, verdict) VALUES (?,?,?,?,?,?,?)",
                      (subject, opened_at or _now(), action, price, est_value, dumps(spec or {}), verdict))
    con.commit()
    return cur.lastrowid


def close(con, id: int, outcome: dict, closed_at: str | None = None, review: str | None = None) -> None:
    """Close deal ``id`` with ``outcome`` (JSON; include ``realised_value`` in VND to be graded)."""
    cur = con.execute("UPDATE deal SET outcome=?, closed_at=?, review=COALESCE(?, review) WHERE id=? AND closed_at IS NULL",
                      (dumps(outcome), closed_at or _now(), review, id))
    if cur.rowcount == 0:
        raise KeyError(f"deal {id} not found or already closed")
    con.commit()


def list_deals(con, open_only: bool = False) -> list[dict]:
    """All paper deals (spec and outcome parsed from JSON), oldest first."""
    q = "SELECT * FROM deal" + (" WHERE closed_at IS NULL" if open_only else "") + " ORDER BY opened_at, id"
    out = []
    for r in rows(con, q):
        r["spec"] = json.loads(r["spec"]) if r["spec"] else {}
        r["outcome"] = json.loads(r["outcome"]) if r["outcome"] else None
        out.append(r)
    return out


def scorecard(con) -> dict:
    """Hit rate and average gaps over closed deals (see the module docstring)."""
    graded, ungraded = [], []
    deals = list_deals(con)
    for d in deals:
        if not d["closed_at"]:
            continue
        rv = (d["outcome"] or {}).get("realised_value")
        if rv is None or not d["price"]:
            ungraded.append(d["id"])
            continue
        p = d["price"]
        hit = rv >= p if d["action"] in _LONG else rv < p
        graded.append({"id": d["id"], "subject": d["subject"], "action": d["action"], "price": p,
                       "est_value": d["est_value"], "realised_value": rv, "hit": hit,
                       "est_gap": (d["est_value"] - p) / p if d["est_value"] is not None else None,
                       "realised_gap": (rv - p) / p,
                       "estimate_error": rv / d["est_value"] - 1 if d["est_value"] else None})

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None
    return {"open": sum(1 for d in deals if not d["closed_at"]), "closed": len(graded) + len(ungraded),
            "graded": len(graded), "ungraded": ungraded,
            "hit_rate": sum(g["hit"] for g in graded) / len(graded) if graded else None,
            "avg_est_gap": mean(g["est_gap"] for g in graded), "avg_realised_gap": mean(g["realised_gap"] for g in graded),
            "avg_estimate_error": mean(g["estimate_error"] for g in graded),
            "avg_abs_estimate_error": mean(abs(g["estimate_error"]) if g["estimate_error"] is not None else None for g in graded),
            "deals": graded}
