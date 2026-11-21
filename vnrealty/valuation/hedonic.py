"""Hedonic regression of price per m² on listing attributes — a second, independent valuation method.

Model (OLS, :func:`vnrealty.stats.ols`)::

    log(price / m²) ~ 1 + ward dummies + ptype dummies + log(area_m2) + alley bucket + corner + legal + month dummies
                      (+ a 'sale' dummy when sale evidence is pooled with asking observations)

Point in time: one row per listing, its latest priced observation with ``seen_at <= as_of`` inside the look-back
window. Prediction returns asking-level price/m² unless told otherwise, and the cited asking→sale haircut is then
applied *explicitly* (recorded in ``detail``). The 10–90% band is lognormal from the residual sigma.

Units: VND, m², VND/m². ``Insufficient`` when fewer than ``min_n`` rows, when the design is singular, or when the
subject's ward/ptype/legal level was not in the fitted data.
"""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from vnrealty.stats import OLSResult, ols
from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation.comps import end_of, load_params, months_back

__all__ = ["HedonicModel", "alley_bucket", "legal_bucket", "fit", "predict", "residual"]

Z90 = 1.2815515655446004  # standard normal 90th percentile


def alley_bucket(alley_m: float | None) -> str:
    """'street' (0 m), 'wide' (≥4.5 m, car), 'mid' (3–4.5 m), 'narrow' (<3 m) or 'unknown' — Đà Nẵng position classes."""
    if alley_m is None:
        return "unknown"
    if alley_m <= 0:
        return "street"
    return "wide" if alley_m >= 4.5 else "mid" if alley_m >= 3 else "narrow"


def legal_bucket(legal: str | None) -> str:
    """'cert' (sổ hồng / sổ đỏ), 'hdmb', 'giay_tay' or 'unknown'."""
    if legal in ("so_hong", "so_do"):
        return "cert"
    return legal if legal in ("hdmb", "giay_tay") else "unknown"


@dataclass
class HedonicModel:
    """A fitted hedonic model. ``levels[cat]`` holds every level seen; the first (sorted) is the omitted base."""
    ols: OLSResult
    names: list[str]
    levels: dict[str, list[str]]
    as_of: str
    n: int
    sigma: float
    r2: float
    latest_month: str
    detail: dict = field(default_factory=dict)


def _load(con: sqlite3.Connection, as_of: str, filters: dict, months: int) -> list[dict]:
    end, start = end_of(as_of), months_back(as_of, months)
    rows = [dict(r) for r in con.execute("""
        SELECT l.id AS listing_id, l.ptype, l.ward_code, l.area_m2, l.alley_m, l.corner, l.legal, o.seen_at, o.price,
               o.kind
        FROM listing l JOIN listing_obs o ON o.listing_id = l.id
        WHERE l.deal = 'sale' AND o.kind = 'asking' AND o.price IS NOT NULL
          AND o.seen_at = (SELECT MAX(o2.seen_at) FROM listing_obs o2 WHERE o2.listing_id = l.id
                           AND o2.kind = 'asking' AND o2.price IS NOT NULL AND o2.seen_at <= ?)
          AND o.seen_at >= ?""", (end, start)).fetchall()]
    sales = [dict(r) for r in con.execute("""
        SELECT s.listing_id, COALESCE(s.ptype, l.ptype) AS ptype, COALESCE(s.ward_code, l.ward_code) AS ward_code,
               COALESCE(s.area_m2, l.area_m2) AS area_m2, l.alley_m, l.corner, l.legal, s.sold_at AS seen_at,
               s.price, 'sale' AS kind
        FROM sale_evidence s LEFT JOIN listing l ON l.id = s.listing_id
        WHERE s.sold_at <= ? AND s.sold_at >= ?""", (end, start)).fetchall()] if filters.get("include_sales", True) else []
    seen, out = set(), []
    for r in sales + rows:
        key = (r["listing_id"], r["kind"]) if r["listing_id"] is not None else None
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        if not r["area_m2"] or r["area_m2"] <= 0 or not r["price"] or r["price"] <= 0 or not r["ward_code"]:
            continue
        if filters.get("ptype") and r["ptype"] != filters["ptype"]:
            continue
        if filters.get("ptypes") and r["ptype"] not in filters["ptypes"]:
            continue
        if filters.get("ward_codes") and r["ward_code"] not in filters["ward_codes"]:
            continue
        out.append(r)
    return out


def _cats(r: dict) -> dict[str, str]:
    return {"ward": r["ward_code"], "ptype": r["ptype"], "alley": alley_bucket(r.get("alley_m")),
            "legal": legal_bucket(r.get("legal")), "month": str(r["seen_at"])[:7], "kind": r.get("kind", "asking")}


def _x(levels: dict[str, list[str]], c: dict[str, str], area: float, corner) -> list[float] | str:
    x = [1.0, math.log(area), 1.0 if corner else 0.0]
    for cat, lv in levels.items():
        if c[cat] not in lv:
            return f"{cat} level {c[cat]!r} not in the fitted data"
        x += [1.0 if c[cat] == v else 0.0 for v in lv[1:]]
    return x


def fit(con: sqlite3.Connection, as_of: str, filters: dict | None = None, min_n: int = 30,
        months: int = 24) -> HedonicModel | Insufficient:
    """Fit the hedonic model on rows visible at ``as_of``.

    ``filters``: optional ``ptype`` / ``ptypes`` / ``ward_codes`` / ``include_sales`` (default True). Returns
    ``Insufficient`` when fewer than ``min_n`` usable rows, or when the design matrix is singular / has no residual
    degrees of freedom.
    """
    rows = _load(con, as_of, filters or {}, months)
    if len(rows) < min_n:
        return Insufficient("hedonic", f"{len(rows)} usable rows (< {min_n}) at {as_of}", {"n": len(rows)})
    cats = [_cats(r) for r in rows]
    levels = {k: sorted({c[k] for c in cats}) for k in ("ward", "ptype", "alley", "legal", "month", "kind")}
    names = ["const", "log_area", "corner"] + [f"{k}={v}" for k, lv in levels.items() for v in lv[1:]]
    X = [_x(levels, c, r["area_m2"], r.get("corner")) for c, r in zip(cats, rows)]
    y = [math.log(r["price"] / r["area_m2"]) for r in rows]
    # drop an all-zero corner column (no corner lots seen) rather than fail as singular
    keep = [j for j in range(len(names)) if j == 0 or any(row[j] != 0 for row in X)]
    Xk = [[row[j] for j in keep] for row in X]
    res = ols(Xk, y, [names[j] for j in keep])
    if res is None:
        return Insufficient("hedonic", "design matrix singular or too few rows for its columns",
                            {"n": len(rows), "k": len(keep)})
    beta_full = {names[j]: b for j, b in zip(keep, res.beta)}
    full = OLSResult([beta_full.get(nm, 0.0) for nm in names], names, res.sigma, res.r2, res.n, res.k)
    return HedonicModel(ols=full, names=names, levels=levels, as_of=as_of, n=len(rows), sigma=res.sigma, r2=res.r2,
                        latest_month=levels["month"][-1],
                        detail={"dropped_columns": [names[j] for j in range(len(names)) if j not in keep],
                                "months": months, "filters": filters or {}})


def _predict_log_ppm(model: HedonicModel, subject: dict, month: str | None, kind: str) -> float | str:
    c = {"ward": subject.get("ward_code"), "ptype": subject.get("ptype"), "alley": alley_bucket(subject.get("alley_m")),
         "legal": legal_bucket(subject.get("legal")), "month": month or model.latest_month, "kind": kind}
    if kind not in model.levels["kind"]:
        c["kind"] = model.levels["kind"][0]
    x = _x(model.levels, c, subject["area_m2"], subject.get("corner"))
    return x if isinstance(x, str) else model.ols.predict(x)


def predict(model: HedonicModel, subject: dict, month: str | None = None, params: dict | None = None,
            haircut: bool = True) -> Estimate | Insufficient:
    """Predict the subject's value (VND) with a lognormal 10–90% band (exp(±1.2816σ)).

    The model predicts asking-level price/m² (unless sale evidence was pooled — then the 'sale' level is used and no
    haircut is applied). With ``haircut=True`` the cited ``asking_to_sale`` factor scales value/lo/hi explicitly
    (lo uses the harsher haircut, hi the milder one).
    """
    if not subject.get("area_m2") or subject["area_m2"] <= 0:
        return Insufficient("hedonic", "subject needs area_m2")
    sale_level = "sale" in model.levels["kind"]
    lp = _predict_log_ppm(model, subject, month, "sale" if sale_level else "asking")
    if isinstance(lp, str):
        return Insufficient("hedonic", lp)
    A = subject["area_m2"]
    v, lo, hi = math.exp(lp) * A, math.exp(lp - Z90 * model.sigma) * A, math.exp(lp + Z90 * model.sigma) * A
    hc_used = None
    if haircut and not sale_level:
        hc = (params or load_params())["asking_to_sale"]
        v, lo, hi = v * hc["value"], lo * hc["lo"], hi * hc["hi"]
        hc_used = {"value": hc["value"], "lo": hc["lo"], "hi": hc["hi"], "basis": hc.get("basis")}
    return Estimate("hedonic", v, lo, hi, n=model.n, as_of=model.as_of,
                    detail={"log_price_m2": lp, "sigma": model.sigma, "r2": model.r2, "month": month or model.latest_month,
                            "level": "sale" if sale_level else "asking", "haircut": hc_used})


def residual(model: HedonicModel, listing_row: dict) -> float | Insufficient:
    """Log residual of a listing against the model: log(actual price/m²) − predicted log(asking price/m²).

    Negative = priced under hedonic value (a screen, not a verdict). ``listing_row`` needs ``price``, ``area_m2``,
    ``ward_code``, ``ptype`` and optionally ``alley_m``, ``corner``, ``legal``, ``seen_at``.
    """
    if not listing_row.get("price") or not listing_row.get("area_m2"):
        return Insufficient("hedonic", "listing needs price and area_m2")
    month = str(listing_row["seen_at"])[:7] if listing_row.get("seen_at") else None
    if month is not None and month not in model.levels["month"]:
        month = None
    lp = _predict_log_ppm(model, listing_row, month, "asking")
    if isinstance(lp, str):
        return Insufficient("hedonic", lp)
    return math.log(listing_row["price"] / listing_row["area_m2"]) - lp
