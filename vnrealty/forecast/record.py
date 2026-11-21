"""The forecast record: publish every forecast, then grade it against what happened.

:func:`record` writes one ``forecast`` row per target month of a fan (series subjects) or of an asset projection.

:func:`grade` scores every forecast made at or before ``as_of`` whose target month is ≤ ``as_of``'s month against the
truth visible at ``as_of``:

* **series subjects** ``series:<source>:<scope_kind>/<scope>:<ptype>`` — the realised value of that source and month
  (latest vintage seen by ``as_of``; source ``splice`` = all sources chain-linked). Strength ``series``.
* **asset subjects** ``listing:<id>`` / ``unit:<id>`` — evidence dated within ±``window_months`` of the target month
  and after the forecast's ``as_of``, in order of strength: ``sale_evidence`` (``sale``), a later ``valuation`` row
  (``valuation``, weaker: an estimate graded against an estimate), the latest asking observation × the cited
  asking→sale haircut (``asking_haircut``, weakest). Weaker truths are labelled and counted at half weight in
  ``n_eff``.

Per model and horizon: ``n``, ``n_eff``, ``mae`` / ``rmse`` / ``bias`` of e = ln(p50 / truth) (positive =
over-forecast), ``coverage`` = share of truths inside [p10, p90], and counts per strength. The output has the same
``models[name][h]`` shape as :func:`vnrealty.forecast.backtest.walk_forward`, so
:func:`vnrealty.forecast.backtest.ensemble_weights` can earn weights from the live record as it grows.

Units: VND or the series unit; errors in log points.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone

from vnrealty.forecast.series import get_series, month_add, splice

__all__ = ["record", "grade", "parse_subject"]


def record(con: sqlite3.Connection, subject: str, as_of: str, model: str, fan: dict, inputs: dict | None = None) -> list[int]:
    """Insert one row per target month of ``fan`` (needs ``months``, ``horizons``, ``p10``, ``p50``, ``p90``); returns
    the row ids. Entries whose p50 is None are not recorded (nothing was forecast)."""
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = json.dumps(inputs or {}, ensure_ascii=False, sort_keys=True, default=str)
    ids = []
    for m, h, a, b, c in zip(fan["months"], fan["horizons"], fan["p10"], fan["p50"], fan["p90"]):
        if b is None:
            continue
        cur = con.execute("INSERT INTO forecast(subject, as_of, model, horizon_months, target_month, p10, p50, p90, "
                          "inputs, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (subject, as_of, model, int(h), m, a, b, c, payload, created))
        ids.append(int(cur.lastrowid))
    con.commit()
    return ids


def parse_subject(subject: str) -> dict:
    """``{'type': 'series', source, scope_kind, scope, ptype}`` or ``{'type': 'listing'|'unit', 'id': ...}``."""
    kind, _, rest = subject.partition(":")
    if kind == "series":
        source, _, rest = rest.partition(":")
        sc, _, ptype = rest.rpartition(":")
        sk, _, scope = sc.partition("/")
        return {"type": "series", "source": source, "scope_kind": sk, "scope": scope, "ptype": ptype or None}
    return {"type": kind, "id": rest}


def _end(as_of: str) -> str:
    return as_of + "T23:59:59.999" if len(as_of) == 10 else as_of


def _series_truth(con, s: dict, month: str, as_of: str, cache: dict) -> float | None:
    key = (s["source"], s["scope_kind"], s["scope"], s["ptype"])
    if key not in cache:
        src = None if s["source"] == "splice" else s["source"]
        got = get_series(con, s["scope_kind"], s["scope"], s["ptype"], source=src, as_of=as_of)
        if s["source"] == "splice":
            cache[key] = dict(splice(list(got.values()))["points"])
        else:
            cache[key] = dict(next(iter(got.values())).points) if len(got) == 1 else {}
    return cache[key].get(month)


def _listing_id(con, s: dict) -> int | None:
    if s["type"] == "listing" and str(s["id"]).isdigit():
        return int(s["id"])
    if s["type"] == "unit":
        r = con.execute("SELECT listing_id FROM unit WHERE id = ?", (s["id"],)).fetchone()
        return r[0] if r and r[0] is not None else None
    return None


def _asset_truth(con, subject: str, s: dict, f_as_of: str, month: str, until: str, window: int,
                 haircut: float | None) -> tuple[float, str] | None:
    lo, hi = month_add(month, -window) + "-01", month_add(month, window) + "-31T23:59:59.999"
    after = _end(f_as_of)
    lid = _listing_id(con, s)
    if lid is not None:
        r = con.execute("SELECT price FROM sale_evidence WHERE listing_id = ? AND sold_at > ? AND sold_at <= ? AND "
                        "sold_at BETWEEN ? AND ? ORDER BY sold_at LIMIT 1", (lid, after, until, lo, hi)).fetchone()
        if r:
            return float(r[0]), "sale"
    r = con.execute("SELECT value FROM valuation WHERE subject = ? AND value IS NOT NULL AND as_of > ? AND as_of <= ? "
                    "AND as_of BETWEEN ? AND ? ORDER BY (method = 'triangulated') DESC, as_of DESC LIMIT 1",
                    (subject, after, until, lo, hi)).fetchone()
    if r:
        return float(r[0]), "valuation"
    if lid is not None and haircut is not None:
        r = con.execute("SELECT price FROM listing_obs WHERE listing_id = ? AND kind = 'asking' AND price IS NOT NULL "
                        "AND seen_at > ? AND seen_at <= ? AND seen_at BETWEEN ? AND ? ORDER BY seen_at DESC LIMIT 1",
                        (lid, after, until, lo, hi)).fetchone()
        if r:
            return float(r[0]) * haircut, "asking_haircut"
    return None


def grade(con: sqlite3.Connection, as_of: str, window_months: int = 3, haircut: float | None = None) -> dict:
    """Grade the forecast record at ``as_of`` (see module doc).

    ``haircut`` is the asking→sale multiplier for asking truths; None reads ``asking_to_sale`` from
    ``reference/market_params.json`` (when that file is unreadable, asking truths are not used). Returns
    ``{as_of, models: {model: {h: {...}}}, n_ungraded}``.
    """
    if haircut is None:
        try:
            from vnrealty.valuation.comps import load_params
            haircut = float(load_params()["asking_to_sale"]["value"])
        except (OSError, KeyError, ValueError):
            haircut = None
    until = _end(as_of)
    cache: dict = {}
    acc: dict[str, dict[int, dict]] = {}
    ungraded = 0
    for r in con.execute("SELECT subject, as_of, model, horizon_months, target_month, p10, p50, p90 FROM forecast "
                         "WHERE as_of <= ? AND target_month <= ? AND p50 IS NOT NULL", (until, as_of[:7])).fetchall():
        s = parse_subject(r["subject"])
        if s["type"] == "series":
            v = _series_truth(con, s, r["target_month"], as_of, cache)
            t = (v, "series") if v else None
        else:
            t = _asset_truth(con, r["subject"], s, r["as_of"], r["target_month"], until, window_months, haircut)
        if t is None or t[0] <= 0:
            ungraded += 1
            continue
        truth, strength = t
        a = acc.setdefault(r["model"], {}).setdefault(int(r["horizon_months"]), {"e": [], "cov": [], "by": {}, "w": 0.0})
        a["e"].append(math.log(r["p50"] / truth))
        if r["p10"] is not None and r["p90"] is not None:
            a["cov"].append(1.0 if r["p10"] <= truth <= r["p90"] else 0.0)
        a["by"][strength] = a["by"].get(strength, 0) + 1
        a["w"] += 1.0 if strength in ("series", "sale") else 0.5
    models = {}
    for m, hs in acc.items():
        models[m] = {}
        for h, a in sorted(hs.items()):
            e = a["e"]
            models[m][h] = {"n": len(e), "n_eff": a["w"], "mae": sum(abs(x) for x in e) / len(e),
                            "rmse": math.sqrt(sum(x * x for x in e) / len(e)), "bias": sum(e) / len(e),
                            "coverage": sum(a["cov"]) / len(a["cov"]) if a["cov"] else None, "by_strength": a["by"]}
    return {"as_of": as_of, "models": models, "n_ungraded": ungraded,
            "note": "valuation and asking_haircut truths are weaker than series or sale truths (half weight in n_eff)"}
