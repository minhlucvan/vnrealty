"""The calibration record: store every published valuation, then grade it against what happened later.

``record`` writes one row to the ``valuation`` table (``Insufficient`` too — value NULL, reason in ``inputs``).
``score`` compares each valuation made at or before ``as_of`` with the first *later* truth visible at ``as_of``:

1. ``sale_evidence`` for the same listing (strength ``sale``) — ground truth;
2. else the latest later asking observation × the cited asking→sale haircut (strength ``asking_haircut``) — weaker,
   labelled, and counted at half weight in ``n_eff``.

Subjects resolvable to a listing: ``listing:<id>`` and ``unit:<id>`` (through ``unit.listing_id``).
Units: VND; errors are fractions of truth.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation.comps import end_of, load_params

__all__ = ["record", "score"]


def record(con: sqlite3.Connection, subject: str, est: Estimate | Insufficient, inputs: dict | None = None,
           as_of: str | None = None) -> int:
    """Insert a valuation row for ``subject`` (``'listing:<id>' | 'unit:<id>' | 'lot:<name>'``); returns its id."""
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if isinstance(est, Insufficient):
        payload = {"insufficient": est.reason, "detail": est.detail, **(inputs or {})}
        row = (subject, as_of or created[:10], est.method, None, None, None, None)
    else:
        payload = {"detail": est.detail, **(inputs or {})}
        row = (subject, as_of or est.as_of or created[:10], est.method, est.value, est.lo, est.hi, est.n)
    cur = con.execute("INSERT INTO valuation(subject, as_of, method, value, lo, hi, n, inputs, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      row + (json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), created))
    con.commit()
    return int(cur.lastrowid)


def _listing_id(con: sqlite3.Connection, subject: str) -> int | None:
    kind, _, ident = subject.partition(":")
    if kind == "listing" and ident.isdigit():
        return int(ident)
    if kind == "unit":
        r = con.execute("SELECT listing_id FROM unit WHERE id = ?", (ident,)).fetchone()
        return r[0] if r and r[0] is not None else None
    return None


def _truth(con: sqlite3.Connection, lid: int, after: str, until: str, haircut: float) -> tuple[float, str] | None:
    r = con.execute("SELECT price FROM sale_evidence WHERE listing_id = ? AND sold_at > ? AND sold_at <= ? "
                    "ORDER BY sold_at LIMIT 1", (lid, end_of(after), until)).fetchone()
    if r:
        return float(r[0]), "sale"
    r = con.execute("SELECT price FROM listing_obs WHERE listing_id = ? AND kind = 'asking' AND price IS NOT NULL "
                    "AND seen_at > ? AND seen_at <= ? ORDER BY seen_at DESC LIMIT 1",
                    (lid, end_of(after), until)).fetchone()
    if r:
        return float(r[0]) * haircut, "asking_haircut"
    return None


def score(con: sqlite3.Connection, as_of: str, params: dict | None = None) -> dict[str, dict]:
    """Per-method grades at ``as_of``: ``n, n_sale, n_asking, n_eff, mape, bias, coverage, mape_sale`` (fractions).

    ``bias`` is mean (estimate − truth) / truth (positive = over-valued); ``coverage`` the share of truths inside
    [lo, hi]. Methods with no gradable valuation are absent. Only rows with ``valuation.as_of <= as_of`` and truths
    with timestamps in (valuation.as_of, as_of] are used.
    """
    hc = (params or load_params())["asking_to_sale"]["value"]
    until = end_of(as_of)
    acc: dict[str, dict] = {}
    for v in con.execute("SELECT subject, as_of, method, value, lo, hi FROM valuation "
                         "WHERE value IS NOT NULL AND as_of <= ?", (until,)).fetchall():
        lid = _listing_id(con, v["subject"])
        if lid is None:
            continue
        t = _truth(con, lid, v["as_of"], until, hc)
        if t is None or t[0] <= 0:
            continue
        truth, strength = t
        a = acc.setdefault(v["method"], {"errs": [], "abs": [], "abs_sale": [], "cover": [], "n_sale": 0, "n_asking": 0})
        e = (v["value"] - truth) / truth
        a["errs"].append(e)
        a["abs"].append(abs(e))
        if strength == "sale":
            a["n_sale"] += 1
            a["abs_sale"].append(abs(e))
        else:
            a["n_asking"] += 1
        if v["lo"] is not None and v["hi"] is not None:
            a["cover"].append(1.0 if v["lo"] <= truth <= v["hi"] else 0.0)
    out = {}
    for meth, a in acc.items():
        n = len(a["errs"])
        out[meth] = {"n": n, "n_sale": a["n_sale"], "n_asking": a["n_asking"], "n_eff": a["n_sale"] + 0.5 * a["n_asking"],
                     "mape": sum(a["abs"]) / n, "bias": sum(a["errs"]) / n,
                     "coverage": sum(a["cover"]) / len(a["cover"]) if a["cover"] else None,
                     "mape_sale": sum(a["abs_sale"]) / len(a["abs_sale"]) if a["abs_sale"] else None,
                     "truth_note": "asking_haircut truths are weaker: later asking × cited haircut"}
    return out
