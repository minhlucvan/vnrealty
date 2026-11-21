"""Screen the whole market: evaluate every active listing, score it, rank it.

:func:`rank_listings` loads each active listing at ``as_of`` (:func:`active_ids`), computes its metrics
(:func:`vnrealty.pricing.metrics.evaluate`) with one shared :class:`~vnrealty.pricing.peers.PeerCache` (one query per
deal kind, one sort per peer scope — a few thousand listings in seconds), scores them
(:func:`vnrealty.pricing.score.pricing_score`) and, for the rows returned, asks the strategy layer
(:func:`vnrealty.strategy.evaluate.evaluate_all`, when importable) for the best way to make money on the listing.

**Active at as_of** (point in time): the listing has an observation of its deal kind with ``seen_at <= as_of``, the
latest one within ``active_days`` (90) of ``as_of``, and it was not marked gone/sold before ``as_of``.

**Inputs reused, never invented**: a triangulated valuation is read from the ``valuation`` table (latest
``method='triangulated'`` row for ``listing:<id>`` with ``as_of <= as_of``) or passed in ``ctx_overrides
['valuations']``; the hedonic model is fitted once (``hedonic.fit``) unless ``ctx_overrides['hedonic']`` is a model
or False. The strategy layer needs a market value and market assumptions (``ctx_overrides
['strategy_assumptions']``); without them it reports why no strategy could be ranked.
Money VND (VND/month for rentals).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation import hedonic as vhedonic
from vnrealty.valuation.comps import end_of

from . import metrics as M
from .peers import PeerCache, snapshot
from .score import pricing_score
from .zoning import load_params

__all__ = ["active_ids", "rank_listings", "best_strategy", "stored_valuation"]


def active_ids(con: sqlite3.Connection, as_of: str, deal: str = "sale", active_days: int = 90) -> list[int]:
    """Listing ids active at ``as_of`` (see module docstring)."""
    kind = "rent" if deal == "rent" else "asking"
    since = (date.fromisoformat(as_of[:10]) - timedelta(days=active_days)).isoformat()
    rows = con.execute("""
        SELECT l.id FROM listing l
        WHERE l.deal = ?
          AND NOT (l.status IN ('gone', 'sold') AND l.last_seen < ?)
          AND (SELECT MAX(o.seen_at) FROM listing_obs o WHERE o.listing_id = l.id AND o.kind = ? AND o.seen_at <= ?) >= ?
        ORDER BY l.id""", (deal, as_of[:10], kind, end_of(as_of), since)).fetchall()
    return [r[0] for r in rows]


def stored_valuation(con: sqlite3.Connection, listing_id: int, as_of: str) -> Estimate | None:
    """The latest stored triangulated valuation of ``listing:<id>`` with ``as_of <= as_of`` (VND), or None."""
    r = con.execute("SELECT method, value, lo, hi, n, as_of FROM valuation WHERE subject = ? AND method = 'triangulated' "
                    "AND as_of <= ? AND value IS NOT NULL ORDER BY as_of DESC, id DESC LIMIT 1",
                    (f"listing:{listing_id}", end_of(as_of))).fetchone()
    if r is None:
        return None
    return Estimate(r[0], r[1], r[2] if r[2] is not None else r[1], r[3] if r[3] is not None else r[1], n=r[4] or 0,
                    as_of=r[5])


def best_strategy(listing: dict, valuation: Estimate | None, assumptions: dict | None) -> dict:
    """Best strategy for a listing from the strategy layer: ``{available, strategy, score, reason}``.

    ``available`` False (``reason`` 'strategy layer not available') when ``vnrealty.strategy`` cannot be imported.
    """
    try:
        from vnrealty.strategy.evaluate import evaluate_all
    except Exception:  # noqa: BLE001 — the layer may be absent or mid-build
        return {"available": False, "strategy": None, "score": None, "reason": "strategy layer not available"}
    if valuation is None:
        return {"available": True, "strategy": None, "score": None,
                "reason": "no market value (no triangulated valuation) — strategies need market_value"}
    opp = {"price": listing["price"], "market_value": valuation.value, "area_m2": listing.get("area_m2"),
           "ptype": listing.get("ptype")}
    try:
        res = evaluate_all(opp, assumptions or {})
    except Exception as e:  # noqa: BLE001 — report, never crash the screen
        return {"available": True, "strategy": None, "score": None, "reason": f"strategy layer error: {e}"}
    if res.get("ranked"):
        top = res["ranked"][0]
        return {"available": True, "strategy": top["strategy"], "score": top["score"],
                "reason": ("killed: " + "; ".join(k.get("detail", str(k)) if isinstance(k, dict) else str(k)
                                                  for k in top["kill"])) if top.get("kill") else None}
    ex = res.get("excluded") or []
    return {"available": True, "strategy": None, "score": None,
            "reason": "no strategy ranked: " + (ex[0]["reason"] if ex else "none evaluated")}


def rank_listings(con: sqlite3.Connection, as_of: str, filters: dict | None = None, top: int = 20,
                  ctx_overrides: dict | None = None, active_days: int = 90) -> dict:
    """Rank every active listing by pricing score.

    ``filters``: ``ward`` (code or list), ``ptypes`` (list), ``max_price`` / ``min_price`` (VND), ``deal``
    ('sale' default | 'rent'). ``ctx_overrides``: any :func:`vnrealty.pricing.metrics.make_ctx` key applied to every
    listing, plus ``per_listing`` ({id: {...}}), ``valuations`` ({id: Estimate}), ``hedonic`` (model | False),
    ``weights`` ({ptype: {metric: w}}), ``strategy_assumptions`` (dict for the strategy layer).

    Returns ``{as_of, n_active, n_evaluated, n_scored, rows, strategy_layer, hedonic, formula}``; each row: ``id,
    ptype, ward, price, title, key_metric {name, value, unit, percentile, z, scope}, score (None = withheld),
    confidence, withheld_reason, best_strategy, strategy_note, flags, why``. Scored rows first (score desc), then
    withheld rows (confidence desc).
    """
    f = dict(filters or {})
    deal = f.get("deal", "sale")
    o = dict(ctx_overrides or {})
    params = o.pop("params", None) or load_params()
    per = o.pop("per_listing", {}) or {}
    vals = o.pop("valuations", {}) or {}
    weights = o.pop("weights", {}) or {}
    s_assume = o.pop("strategy_assumptions", None)
    hed = o.pop("hedonic", "fit")
    hed_note = "not used"
    if hed == "fit":
        hed = vhedonic.fit(con, as_of)
        hed_note = f"fitted (n={hed.n}, r²={hed.r2:.2f})" if not isinstance(hed, Insufficient) else f"insufficient: {hed.reason}"
    elif hed:
        hed_note = "given"
    else:
        hed = None
    base = M.make_ctx(con, as_of, params=params, hedonic=hed, **o)
    cache = base["cache"]
    wards = f.get("ward")
    wards = {wards} if isinstance(wards, str) else set(wards) if wards else None
    ptypes = set(f["ptypes"]) if f.get("ptypes") else None
    ids = active_ids(con, as_of, deal, active_days)
    rows = []
    for lid in ids:
        lst = snapshot(con, lid, as_of)
        if isinstance(lst, Insufficient):
            continue
        if wards and lst.get("ward_code") not in wards:
            continue
        if ptypes and lst.get("ptype") not in ptypes:
            continue
        pr = lst.get("price")
        if f.get("max_price") is not None and (pr is None or pr > f["max_price"]):
            continue
        if f.get("min_price") is not None and (pr is None or pr < f["min_price"]):
            continue
        v = vals.get(lid) or stored_valuation(con, lid, as_of)
        ctx = {**base, "cache": cache, "valuation": v, **per.get(lid, {})}
        mets = M.evaluate(lst, ctx)
        t = "rent" if deal == "rent" else (lst.get("ptype") or "other")
        sc = pricing_score(mets, t, weights.get(t), params)
        key = M.KEY_METRIC.get(t, "price_m2")
        ke = mets.get(key) or {}
        peer = ke.get("peer") or {}
        rows.append({"id": lid, "ptype": lst.get("ptype"), "ward": lst.get("ward_code"), "price": pr,
                     "title": lst.get("title"),
                     "key_metric": {"name": key, "value": ke.get("value"), "unit": ke.get("unit"),
                                    "percentile": peer.get("percentile"), "z": peer.get("z"), "scope": peer.get("scope"),
                                    "insufficient": ke.get("insufficient")},
                     "score": sc["score"], "confidence": sc["confidence"], "withheld_reason": sc["withheld_reason"],
                     "flags": sc["flags"], "why": sc["why"], "_lst": lst, "_val": v})
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] if r["score"] is not None else r["confidence"])))
    out = rows[:top]
    layer = None
    for r in out:
        bs = best_strategy(r.pop("_lst"), r.pop("_val"), s_assume)
        layer = "available" if bs["available"] else "strategy layer not available"
        r["best_strategy"], r["strategy_note"] = bs["strategy"], bs["reason"]
    for r in rows[top:]:
        r.pop("_lst", None), r.pop("_val", None)
    if layer is None:
        layer = best_strategy({"price": 1.0}, None, None)["reason"] if out == [] else "available"
        layer = "available" if layer != "strategy layer not available" else layer
    return {"as_of": as_of, "n_active": len(ids), "n_evaluated": len(rows),
            "n_scored": sum(r["score"] is not None for r in rows), "rows": out, "strategy_layer": layer,
            "hedonic": hed_note, "formula": "score = Σ w·points / Σ w (see vnrealty.pricing.score); withheld when "
                                            "confidence < " + str(params["score_min_confidence"]["value"])}
