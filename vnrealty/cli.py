"""`vnr` — the desk's command line. Agents orchestrate through it; every number it prints comes from a library.

    python3 -m vnrealty.cli [--db PATH] [--as-of YYYY-MM-DD] [--json] <command> …

Global flags may also follow the command (``vnr value 12 --as-of 2026-11-01 --json``). ``--as-of`` defaults to
today and is printed in every result, so point in time is explicit. ``--json`` prints one object per command:
``{"command", "as_of", "status", …library results…}``; dataclasses become dicts and an Estimate / Insufficient carries
``"status": "ok" | "insufficient"``. Exit codes: 0 ok, 1 error, 2 insufficient or unavailable (a module another
builder has not finished yet answers ``{"status": "unavailable", "reason": …}``).

SUBJECT is ``listing:<id>`` or a bare id (a listing), ``unit:<id>`` (an owned unit) or a path to a lot JSON file.
"""
from __future__ import annotations

import math

import argparse
import dataclasses
import json
import sqlite3
import sys
from pathlib import Path

from vnrealty.cli_support import compose as C
from vnrealty.cli_support.common import (CliError, Unavailable, call_flex, guarded, jsonable, load_json, now_ts,
                                         print_human, resolve_subject, status_of, subject_key, today)
from vnrealty.store import db as store
from vnrealty.types import Estimate, Insufficient

__all__ = ["main", "build_parser"]


class Raw(str):
    """Plain text printed as-is in human mode (e.g. a browser script)."""


class Ctx:
    def __init__(self, a):
        self.db = Path(a.db) if a.db != ":memory:" else a.db
        self.as_of_explicit = a.as_of is not None
        self.as_of = a.as_of or today()
        self.json = a.json
        self._con = None
        self.data_dir = (Path(a.db).resolve().parent if a.db != ":memory:" else store.REPO / "data")

    @property
    def con(self) -> sqlite3.Connection:
        if self._con is None:
            self._con = store.connect(self.db)
            if self._con.execute("SELECT COUNT(*) FROM ward").fetchone()[0] == 0:
                from vnrealty.geo.wards import seed_wards
                seed_wards(self._con)
        return self._con

    def close(self):
        if self._con is not None:
            self._con.close()


# =================================================================== helpers

def _ward(ctx, text: str | None) -> str | None:
    """A ward code from a code or a printed name; CliError when it cannot be placed."""
    if text in (None, "", "city"):
        return None
    from vnrealty.geo.wards import load_wards, match_ward_detail
    if text in {w["code"] for w in load_wards()}:
        return text
    if ctx.con.execute("SELECT 1 FROM ward WHERE code = ?", (text,)).fetchone():
        return text
    m = match_ward_detail(text)
    if not m.get("code"):
        raise CliError(f"cannot place ward {text!r} ({m.get('how')}; candidates {m.get('candidates')})")
    return m["code"]


def _num(s) -> float | None:
    if s is None:
        return None
    t = str(s).strip().lower().replace(",", "").replace("_", "")
    mult = 1.0
    for suf, k in (("b", 1e9), ("ty", 1e9), ("tỷ", 1e9), ("m", 1e6), ("tr", 1e6), ("k", 1e3)):
        if t.endswith(suf) and t[:-len(suf)].replace(".", "", 1).replace("e", "", 1).lstrip("-").isdigit():
            t, mult = t[:-len(suf)], k
            break
    try:
        return float(t) * mult
    except ValueError:
        raise CliError(f"not a number: {s!r}")


def _status(x) -> str:
    return status_of(x)


def _end(as_of: str) -> str:
    return as_of if len(as_of) > 10 else as_of + "T99"


# =================================================================== browser / capture / ingest

def cmd_browser_list(ctx, a):
    from vnrealty.browser import list_scripts
    return {"scripts": list_scripts()}


def cmd_browser_script(ctx, a):
    from vnrealty.browser import script
    try:
        js = script(a.name)
    except KeyError:
        from vnrealty.browser import list_scripts
        raise CliError(f"unknown script {a.name!r}; one of {list_scripts()}")
    return {"name": a.name, "script": js} if ctx.json else Raw(js)


def cmd_capture_save(ctx, a):
    from vnrealty.browser import save_capture, save_text_capture
    if a.text:
        p = Path(a.text)
        if not p.exists():
            raise CliError(f"no such file {a.text}")
        if not (a.url and a.site):
            raise CliError("a text capture needs --url and --site")
        headers = {"url": a.url, "site": a.site, "seen_at": a.seen_at or now_ts(), "kind": a.kind or "search",
                   "deal": a.deal, "search": a.search}
        path = save_text_capture(headers, p.read_text(encoding="utf-8"), ctx.data_dir)
        return {"path": str(path), "format": "text"}
    if not a.file:
        raise CliError("capture save needs FILE (a script's JSON) or --text FILE")
    p = Path(a.file)
    if not p.exists():
        raise CliError(f"no such file {a.file}")
    raw = p.read_text(encoding="utf-8")
    try:
        obj = json.loads(raw)
    except ValueError:
        obj = raw
    if a.search and isinstance(obj, dict):
        obj.setdefault("search", a.search)
    path = save_capture(obj, ctx.data_dir)
    return {"path": str(path), "format": "json"}


def cmd_ingest(ctx, a):
    from vnrealty.listings.ingest import ingest_dir, ingest_file
    p = Path(a.path)
    if not p.exists():
        raise CliError(f"no such path {a.path}")
    r = ingest_dir(ctx.con, p) if p.is_dir() else ingest_file(ctx.con, p)
    return {"path": str(p), **r}


# =================================================================== listings / search / track / coverage

def cmd_listings(ctx, a):
    if a.action:
        if a.action[0] != "watch" or len(a.action) != 2:
            raise CliError("usage: listings watch ID [--off]")
        lid = int(a.action[1].split(":")[-1])
        cur = ctx.con.execute("UPDATE listing SET watch = ? WHERE id = ?", (0 if a.off else 1, lid))
        ctx.con.commit()
        if cur.rowcount == 0:
            raise CliError(f"no listing {lid}")
        return {"listing_id": lid, "watch": not a.off}
    rows = C.listing_rows(ctx.con, ctx.as_of, deal=a.deal, ward=_ward(ctx, a.ward), ptype=a.ptype,
                          min_price=_num(a.min_price), max_price=_num(a.max_price), watched=a.watched, limit=a.limit)
    return {"n": len(rows), "kind": "rent" if a.deal == "rent" else "asking", "listings": rows}


def cmd_search_add(ctx, a):
    from vnrealty.listings.track import add_search
    crit = load_json(a.criteria, "criteria") if a.criteria else None
    return {"id": add_search(ctx.con, a.name, a.site, a.url, crit), "name": a.name}


def cmd_search_list(ctx, a):
    from vnrealty.listings.track import list_searches
    return {"searches": list_searches(ctx.con)}


def cmd_search_touch(ctx, a):
    from vnrealty.listings.track import touch_search
    at = a.at or (ctx.as_of if ctx.as_of_explicit else now_ts())
    try:
        touch_search(ctx.con, a.name, at)
    except KeyError:
        raise CliError(f"no saved search {a.name!r}")
    return {"name": a.name, "last_run": at}


def cmd_track(ctx, a):
    from vnrealty.listings.track import changes, mark_gone
    if a.action == "mark-gone":
        ids = mark_gone(ctx.con, ctx.as_of, a.days)
        return {"marked_gone": ids, "n": len(ids), "days": a.days}
    if a.action:
        raise CliError("usage: track [--since DATE] | track mark-gone [--days N]")
    since = a.since or C.days_before(ctx.as_of, 7)
    return {"since": since, **changes(ctx.con, since, ctx.as_of)}


def cmd_coverage(ctx, a, min_n: int = 5):
    q = ("SELECT l.ward_code, l.ptype, l.deal, substr(o.seen_at, 1, 7) AS month, COUNT(DISTINCT l.id) AS listings, "
         "COUNT(*) AS obs, SUM(o.price IS NOT NULL) AS priced FROM listing l JOIN listing_obs o ON o.listing_id = l.id "
         "WHERE o.seen_at <= ?")
    args: list = [_end(ctx.as_of)]
    w = _ward(ctx, a.ward)
    if w:
        q += " AND l.ward_code = ?"
        args.append(w)
    q += " GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4"
    cells = store.rows(ctx.con, q, tuple(args))
    for c in cells:
        c["thin"] = c["listings"] < min_n
    by_ward: dict = {}
    for c in cells:
        k = c["ward_code"] or "(unplaced)"
        b = by_ward.setdefault(k, {"ward_code": k, "listings": 0, "obs": 0, "cells": 0, "thin_cells": 0})
        b["obs"] += c["obs"]
        b["cells"] += 1
        b["thin_cells"] += int(c["thin"])
    for k, b in by_ward.items():
        b["listings"] = ctx.con.execute(
            "SELECT COUNT(DISTINCT l.id) FROM listing l JOIN listing_obs o ON o.listing_id = l.id WHERE o.seen_at <= ? "
            + ("AND l.ward_code IS NULL" if k == "(unplaced)" else "AND l.ward_code = ?"),
            (_end(ctx.as_of),) if k == "(unplaced)" else (_end(ctx.as_of), k)).fetchone()[0]
    return {"thin_threshold": min_n, "by_ward": sorted(by_ward.values(), key=lambda b: -b["listings"]),
            "cells": cells}


def cmd_wards_seed(ctx, a):
    from vnrealty.geo.wards import seed_wards
    return {"seeded": seed_wards(ctx.con)}


def cmd_wards_match(ctx, a):
    from vnrealty.geo.wards import match_ward_detail
    return {"text": a.text, **match_ward_detail(a.text)}


# =================================================================== market

def _market_read(ctx, ward: str | None, ptype: str | None, deal: str) -> dict:
    from vnrealty.market.index import hedonic_index, ppm2_table, repeat_index
    from vnrealty.market.landscape import summary
    from vnrealty.market.rent import gross_yield, rent_ppm2
    if ward:
        table = [r for r in ppm2_table(ctx.con, ctx.as_of, ("ward_code", "ptype")) if r["ward_code"] == ward]
    else:
        table = ppm2_table(ctx.con, ctx.as_of, ("ptype",))
    if ptype:
        table = [r for r in table if r.get("ptype") == ptype]
    return {"scope": ward or "city", "ward_code": ward, "ptype": ptype, "kind": "asking",
            "ppm2": table,
            "repeat_index": repeat_index(ctx.con, ctx.as_of, ward_code=ward, ptype=ptype),
            "hedonic_index": hedonic_index(ctx.con, ctx.as_of),
            "landscape": summary(ctx.con, ctx.as_of, ward, ptype, deal),
            "rent": rent_ppm2(ctx.con, ward, ptype, ctx.as_of),
            "gross_yield": gross_yield(ctx.con, ward, ptype, ctx.as_of)}


def _yields(ctx, ward: str | None, ptype: str | None) -> list[dict]:
    from vnrealty.market.rent import gross_yield
    q = "SELECT DISTINCT ward_code, ptype FROM listing WHERE deal = 'rent' AND ward_code IS NOT NULL"
    args: list = []
    if ward:
        q += " AND ward_code = ?"
        args.append(ward)
    if ptype:
        q += " AND ptype = ?"
        args.append(ptype)
    combos = [(r[0], r[1]) for r in ctx.con.execute(q + " ORDER BY 1, 2", args)]
    if not ward:
        combos += sorted({(None, p) for _, p in combos})
    out = []
    for w, p in combos:
        g = gross_yield(ctx.con, w, p, ctx.as_of)
        row = {"ward_code": w or "city", "ptype": p}
        if isinstance(g, Insufficient):
            row.update({"yield": None, "status": "insufficient", "reason": g.reason, **g.detail})
        else:
            row.update({"status": "ok", **{k: v for k, v in g.items() if k not in ("ward", "ptype", "as_of")}})
        row["ward_code"] = w or "city"
        out.append(row)
    return out


def _save_index(ctx, idx: dict, source: str, ward: str | None, ptype: str | None) -> dict:
    pts = [(m["month"], m["index"]) for m in idx["months"] if m.get("index") is not None]
    if not pts:
        return {"saved": 0, "reason": "no index months"}
    scope_kind, scope = ("ward", ward) if ward else ("city", "da-nang")
    from vnrealty.forecast.series import add_points
    n = add_points(ctx.con, source, scope_kind, scope, ptype, pts, "index", None, ctx.as_of, kind="asking",
                   notes=f"vnr market index --save ({idx.get('method')})")
    return {"saved": n, "source": source, "scope_kind": scope_kind, "scope": scope, "ptype": ptype}


def cmd_market(ctx, a):
    from vnrealty.market.index import hedonic_index, repeat_index
    from vnrealty.market.rent import gross_yield, rent_ppm2
    target = a.target or "city"
    ptype = a.ptype
    if target == "yields":
        return {"kind": "asking gross yield (before vacancy, costs, tax, haircut)",
                "yields": _yields(ctx, _ward(ctx, a.ward), ptype)}
    if target == "rents":
        w = _ward(ctx, a.ward)
        r = rent_ppm2(ctx.con, w, ptype, ctx.as_of)
        g = gross_yield(ctx.con, w, ptype, ctx.as_of)
        return {"ward_code": w, "ptype": ptype, "rent": r, "gross_yield": g, "status": _status(r)}
    if target == "index":
        w = _ward(ctx, a.ward)
        rep = repeat_index(ctx.con, ctx.as_of, ward_code=w, ptype=ptype)
        hed = hedonic_index(ctx.con, ctx.as_of)
        out = {"ward_code": w, "ptype": ptype, "repeat_index": rep, "hedonic_index": hed}
        if a.save:
            saved = []
            if not isinstance(rep, Insufficient):
                saved.append(_save_index(ctx, rep, "own-repeat", w, ptype))
            if not isinstance(hed, Insufficient) and w is None and ptype is None:
                saved.append(_save_index(ctx, hed, "own-hedonic", None, None))
            out["saved"] = saved
        out["status"] = "insufficient" if isinstance(rep, Insufficient) and isinstance(hed, Insufficient) else "ok"
        return out
    w = _ward(ctx, target if target != "city" else None)
    return _market_read(ctx, w, ptype, a.deal)


# =================================================================== sales

def cmd_sale_add(ctx, a):
    lid = int(str(a.listing).split(":")[-1]) if a.listing else None
    ward, ptype, area = _ward(ctx, a.ward), a.ptype, a.area
    if lid:
        r = ctx.con.execute("SELECT ward_code, ptype, area_m2 FROM listing WHERE id = ?", (lid,)).fetchone()
        if r is None:
            raise CliError(f"no listing {lid}")
        ward, ptype, area = ward or r[0], ptype or r[1], area or r[2]
    cur = ctx.con.execute(
        "INSERT INTO sale_evidence(listing_id, sold_at, price, ward_code, ptype, area_m2, source, url, confidence, notes)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (lid, a.sold_at, _num(a.price), ward, ptype, area, a.source, a.url, a.confidence, a.notes))
    ctx.con.commit()
    return {"id": cur.lastrowid, "listing_id": lid, "price": _num(a.price), "sold_at": a.sold_at,
            "confidence": a.confidence}


def cmd_sale_list(ctx, a):
    q, args = "SELECT * FROM sale_evidence WHERE sold_at <= ?", [_end(ctx.as_of)]
    if a.ward:
        q += " AND ward_code = ?"
        args.append(_ward(ctx, a.ward))
    if a.listing:
        q += " AND listing_id = ?"
        args.append(int(str(a.listing).split(":")[-1]))
    return {"sales": store.rows(ctx.con, q + " ORDER BY sold_at", tuple(args))}


# =================================================================== valuation

def cmd_value(ctx, a):
    s = resolve_subject(ctx.con, a.subject, ctx.as_of)
    return C.run_value(ctx.con, s, ctx.as_of, record=not a.no_record)


def cmd_comps(ctx, a):
    from vnrealty.valuation.comps import adjust, load_params, select_comps, value_by_comps
    s = resolve_subject(ctx.con, a.subject, ctx.as_of)
    p = load_params()
    raw = select_comps(ctx.con, s, ctx.as_of, radius_km=a.km, months=a.months)
    adj = [adjust(c, s, p) for c in raw]
    est = value_by_comps(ctx.con, s, ctx.as_of, radius_km=a.km, months=a.months)
    return {"subject": s, "comps": adj, "estimate": est, "haircut": p.get("asking_to_sale"), "status": _status(est)}


def _anchors(ctx, s: dict) -> list[dict]:
    from vnrealty.listings.track import history
    out = []
    if s.get("listing_id"):
        for o in history(ctx.con, int(s["listing_id"])):
            if o["price"] and o["seen_at"] <= _end(ctx.as_of) and o["kind"] in ("asking", "sale"):
                out.append({"month": o["seen_at"][:7], "value": o["price"],
                            "label": "fact" if o["kind"] == "sale" else "estimate",
                            "source": f"{o['kind']} {o['site']} {o['url'] or ''}".strip()})
        for r in ctx.con.execute("SELECT sold_at, price, source FROM sale_evidence WHERE listing_id = ? AND sold_at <= ?",
                                 (s["listing_id"], _end(ctx.as_of))):
            out.append({"month": r[0][:7], "value": r[1], "label": "fact", "source": f"sale_evidence: {r[2]}"})
    if s.get("cost") and s.get("bought_at") and str(s["bought_at"]) <= _end(ctx.as_of):
        out.append({"month": str(s["bought_at"])[:7], "value": s["cost"], "label": "fact", "source": "unit purchase"})
    for an in s.get("anchors") or []:
        out.append({"month": str(an[0])[:7], "value": float(an[1]), "label": an[2] if len(an) > 2 else "estimate",
                    "source": an[3] if len(an) > 3 else "lot file"})
    return sorted(out, key=lambda x: x["month"])


def cmd_history(ctx, a):
    from vnrealty.history.reconstruct import reconstruct
    s = resolve_subject(ctx.con, a.subject, ctx.as_of)
    anchors = _anchors(ctx, s)
    idx = C.index_series(ctx.con, ctx.as_of, s.get("ward_code"), s.get("ptype"), scope=a.index)
    out = {"subject": s, "anchors": anchors, "index_source": idx["source"], "index_tried": idx["tried"]}
    if not anchors:
        out["history"] = Insufficient("reconstruct", "no dated anchors (listing observations, sales or purchase)")
    elif not idx["series"]:
        out["history"] = Insufficient("reconstruct", "no index series to link anchors", {"tried": idx["tried"]})
    else:
        y0 = int(anchors[0]["month"][:4])
        years = list(range(min(y0, int(idx["series"][0][0][:4])), int(ctx.as_of[:4]) + 1))
        out["history"] = reconstruct([(x["month"], x["value"], x["label"]) for x in anchors], idx["series"], years)
    out["status"] = _status(out["history"])
    return out


# =================================================================== infra

def cmd_infra_seed(ctx, a):
    from vnrealty.infra.catalog import seed_projects
    return {"seeded": seed_projects(ctx.con)}


def _latlng(text: str) -> tuple[float, float]:
    try:
        la, ln = (float(x) for x in text.split(","))
        return la, ln
    except ValueError:
        raise CliError(f"expected LAT,LNG, got {text!r}")


def cmd_infra_near(ctx, a):
    from vnrealty.infra.catalog import near
    la, ln = _latlng(a.latlng)
    return {"lat": la, "lng": ln, "km": a.km, "projects": near(ctx.con, la, ln, a.km)}


def cmd_infra_catalysts(ctx, a):
    from vnrealty.infra.catalog import catalysts_for
    s = resolve_subject(ctx.con, a.subject, ctx.as_of)
    if s.get("lat") is None or s.get("lng") is None:
        return {"subject": s["subject"], "status": "insufficient",
                "reason": "subject has no coordinates (capture the detail page or a maps capture)"}
    return {"subject": s["subject"], "km": a.km, **catalysts_for(ctx.con, s["lat"], s["lng"], a.km)}


def cmd_infra_add(ctx, a):
    from vnrealty.infra.catalog import add_evidence, upsert_project
    p = load_json(a.file, "project") if a.file else {}
    for k in ("id", "name_vi", "name_en", "kind", "status", "lat", "lng", "radius_km", "budget_vnd", "start_year",
              "done_year", "p_done", "uplift"):
        v = getattr(a, k, None)
        if v is not None:
            p[k] = v
    if a.wards:
        p["ward_codes"] = [w.strip() for w in a.wards.split(",")]
    if a.basis:
        p["basis"] = load_json(a.basis, "basis") if a.basis.strip()[:1] == "{" else {"text": a.basis}
    if not p.get("id"):
        raise CliError("infra add needs --id (or an id in --file)")
    pid = upsert_project(ctx.con, p)
    ev = None
    if a.url:
        ev = add_evidence(ctx.con, pid, a.url, title=a.title, claim=a.claim, seen_at=ctx.as_of)
    return {"id": pid, "evidence_id": ev}


def cmd_infra_cite(ctx, a):
    from vnrealty.infra.catalog import add_evidence
    if not ctx.con.execute("SELECT 1 FROM project WHERE id = ?", (a.id,)).fetchone():
        raise CliError(f"no project {a.id!r}")
    eid = add_evidence(ctx.con, a.id, a.url, title=a.title, published=a.published, claim=a.claim, seen_at=ctx.as_of)
    return {"project_id": a.id, "evidence_id": eid, "duplicate": eid is None}


def cmd_infra_zoning(ctx, a):
    from vnrealty.infra.catalog import landuse_codes, zoning_note
    key = subject_key(a.subject)
    if a.action == "add":
        if not a.code or not a.source:
            raise CliError("infra zoning add needs --code and --source")
        note = zoning_note([c.strip() for c in a.code.split(",")], a.source, ctx.as_of, note=a.note)
        if a.plan:
            note["plan"] = a.plan
        cur = ctx.con.execute("INSERT INTO journal(at, kind, subject, body) VALUES (?, 'zoning', ?, ?)",
                              (ctx.as_of, key, store.dumps(note)))
        ctx.con.commit()
        return {"subject": key, "journal_id": cur.lastrowid, "zoning": note}
    rows = store.rows(ctx.con, "SELECT id, at, body FROM journal WHERE kind = 'zoning' AND subject = ? AND at <= ? "
                               "ORDER BY at, id", (key, _end(ctx.as_of)))
    codes = landuse_codes()
    recs = []
    for r in rows:
        b = json.loads(r["body"])
        b["meaning"] = {c: codes.get(c) for c in b.get("codes", [])}
        recs.append({"id": r["id"], "at": r["at"], **b})
    if not recs:
        return {"subject": key, "status": "insufficient", "reason": "no zoning recorded for this subject",
                "records": []}
    return {"subject": key, "latest": recs[-1], "records": recs}


# =================================================================== projection

def cmd_project(ctx, a):
    from vnrealty.infra.catalog import catalysts_for
    from vnrealty.projection.catalysts import hold_vs_sell, paths
    from vnrealty.projection.montecarlo import simulate
    s = resolve_subject(ctx.con, a.subject, ctx.as_of)
    v = C.run_value(ctx.con, s, ctx.as_of, record=False)
    comb = v["combined"]
    out = {"subject": s, "value": comb, "years": a.years}
    if isinstance(comb, Insufficient):
        out.update(status="insufficient", reason="no value today: " + comb.reason)
        return out
    if a.drift is not None and a.vol is not None:
        mk = {"drift": a.drift, "vol": a.vol, "basis": "flags --drift/--vol"}
    else:
        idx = C.index_series(ctx.con, ctx.as_of, s.get("ward_code"), s.get("ptype"))
        mk = C.drift_vol(idx["series"]) if idx["series"] else \
            Insufficient("drift_vol", "no own index series; pass --drift and --vol", {"tried": idx["tried"]})
        if isinstance(mk, dict):
            mk["index_source"] = idx["source"]
            if a.drift is not None:
                mk["drift"] = a.drift
            if a.vol is not None:
                mk["vol"] = a.vol
    out["market"] = mk
    if isinstance(mk, Insufficient):
        out["status"] = "insufficient"
        out["reason"] = mk.reason
        return out
    cats = {"catalysts": [], "skipped": []}
    if s.get("lat") is not None and s.get("lng") is not None:
        cats = catalysts_for(ctx.con, s["lat"], s["lng"], a.km)
    else:
        cats["skipped"].append({"id": None, "reason": "subject has no coordinates: catalysts not searched"})
    out["catalysts"] = cats
    y0 = int(ctx.as_of[:4])
    pth = paths({"y1": mk["drift"], "later": mk["drift"]}, cats["catalysts"], a.years, y0)
    out["paths"] = pth
    out["monte_carlo"] = simulate(comb.value, a.years, mk["drift"], mk["vol"], cats["catalysts"], n=a.n,
                                  start_year=y0, hurdle_rate=a.deposit_rate)
    if a.deposit_rate is None:
        out["hold_vs_sell"] = Insufficient("hold_vs_sell", "pass --deposit-rate (annual fraction) to compare with "
                                                           "selling now and holding cash on deposit")
    else:
        share = float(s.get("share") or 1.0)
        out["hold_vs_sell"] = hold_vs_sell(comb.value, share, C.sell_costs(), a.deposit_rate, pth["base"],
                                           holding_cost=a.holding_cost, start_year=y0)
    out["status"] = "ok"
    return out


# =================================================================== deals

def _deal_payload(d) -> dict:
    from vnrealty.deal.engine import analyse, stress
    m = analyse(d)
    st = stress(d)
    keys = ("irr", "npv", "profit", "cash_in", "peak_cash_out", "passes", "reasons")
    return {"deal": d, "metrics": {k: v for k, v in m.items() if k != "years"},
            "stress": {name: {**{k: r[k] for k in keys}, "dscr": r["stable"]["dscr"], "stable_cash": r["stable"]["cash"]}
                       for name, r in st.items()},
            "yearly": m["years"]}


def cmd_deal(ctx, a):
    if a.file == "preset":
        if not a.name:
            raise CliError(f"usage: deal preset NAME (one of {sorted(C.PRESETS)})")
        subj = resolve_subject(ctx.con, a.subject, ctx.as_of) if a.subject else None
        t = C.preset_template(a.name, subj)
        out = Path(a.out) if a.out else ctx.data_dir / "deals" / f"{a.name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"preset": a.name, "path": str(out), "fill": t["_fill"], "template": t}
    raw, d = C.load_deal(a.file)
    if isinstance(d, Insufficient):
        return {"file": a.file, "status": "insufficient", "deal": d}
    return {"file": a.file, **_deal_payload(d)}


def _ev_payload(raw: dict, d, scenarios_src: str | None, kill_src: str | None) -> dict:
    from vnrealty.deal.engine import analyse
    from vnrealty.deal.ev import default_scenarios, ev, kill_triggers
    sc = load_json(scenarios_src, "scenarios") if scenarios_src else raw.get("scenarios")
    if isinstance(sc, dict):
        sc = sc.get("scenarios")
    basis = "file" if sc else "default_scenarios (judgement priors)"
    sc = sc or default_scenarios(d)
    res = ev(d, sc)
    rules = load_json(kill_src, "kill rules") if kill_src else raw.get("kill") or \
        {"dscr_lt": d.dscr_min, "cash_lt": 0.0, "irr_lt": d.hurdle}
    base = analyse(d)
    fired = kill_triggers(base, {k: v for k, v in rules.items() if k != "p_loss_gt"})
    if "p_loss_gt" in rules or not kill_src:
        fired += kill_triggers(res, {"p_loss_gt": rules.get("p_loss_gt", 0.25)})
    return {"scenario_basis": basis, "ev": res, "kill_rules": rules, "kill": fired,
            "base": {k: base[k] for k in ("irr", "npv", "profit", "passes", "reasons", "loan_max")}}


def cmd_ev(ctx, a):
    raw, d = C.load_deal(a.file)
    if isinstance(d, Insufficient):
        return {"file": a.file, "status": "insufficient", "deal": d}
    return {"file": a.file, **_ev_payload(raw, d, a.scenarios, a.kill)}


def _compare_items(ctx, args: list[str], template: str | None) -> tuple[list, list]:
    items, problems = [], []
    tpl = C.load_deal(template) if template else None
    for t in args:
        if t.endswith(".json") and Path(t).exists() and not (load_json(t).get("ptype") and "price" not in load_json(t)):
            raw, d = C.load_deal(t)
            if isinstance(d, Insufficient):
                problems.append({"item": t, "reason": d.reason})
                continue
            items.append({"name": raw.get("name") or Path(t).stem, "deal": d, "est_value": raw.get("est_value"),
                          "area_m2": raw.get("area_m2"), "extra": {"source": t}})
            continue
        s = resolve_subject(ctx.con, t, ctx.as_of)
        if tpl is None:
            problems.append({"item": t, "reason": "a listing/unit needs --deal TEMPLATE.json (loan, rent, rates) "
                                                  "to be compared on IRR/DSCR"})
            continue
        traw, td = tpl
        if isinstance(td, Insufficient) and set(td.detail.get("missing", [])) - {"price", "value_after"}:
            problems.append({"item": t, "reason": "template: " + td.reason})
            continue
        v = C.run_value(ctx.con, s, ctx.as_of, record=False)
        est = v["combined"].value if isinstance(v["combined"], Estimate) else None
        if s.get("ask") is None:
            problems.append({"item": t, "reason": "no asking price"})
            continue
        fields = {k: traw[k] for k in traw if not k.startswith("_")}
        fields["price"] = s["ask"]
        if fields.get("value_after") is None:
            if est is None:
                problems.append({"item": t, "reason": "no triangulated value for value_after"})
                continue
            fields["value_after"] = est
        d = C.deal_from_dict(fields)
        if isinstance(d, Insufficient):
            problems.append({"item": t, "reason": d.reason})
            continue
        items.append({"name": s["subject"], "deal": d, "est_value": est, "area_m2": s.get("area_m2"),
                      "extra": {"legal": s.get("legal"), "ward_code": s.get("ward_code"), "ptype": s.get("ptype")}})
    return items, problems


def cmd_compare(ctx, a):
    from vnrealty.plan.compare import compare
    items, problems = _compare_items(ctx, a.subjects, a.deal)
    if len(items) < 1:
        return {"status": "insufficient", "reason": "nothing comparable", "problems": problems}
    res = compare(items)
    return {**res, "problems": problems, "status": "ok" if not problems else "ok"}


# =================================================================== strategy

def _opportunity(path: str, assumptions_src: str | None) -> tuple[dict, dict]:
    d = load_json(path, "opportunity")
    if not isinstance(d, dict):
        raise CliError("an opportunity file is a JSON object")
    if "opportunity" in d:
        opp, ass = dict(d["opportunity"]), dict(d.get("assumptions") or {})
    else:
        opp, ass = dict(d), {}
    if assumptions_src:
        ass.update(load_json(assumptions_src, "assumptions"))
    return opp, ass


def _strategy_eval(ctx, path, assumptions_src=None, profile_src=None, strategies=None, hurdle=None) -> dict:
    from vnrealty.strategy.evaluate import evaluate_all
    opp, ass = _opportunity(path, assumptions_src)
    prof, psrc = C.load_profile(profile_src, ctx.data_dir)
    names = [s.strip() for s in strategies.split(",")] if strategies else None
    res = evaluate_all(opp, ass, strategies=names, hurdle=hurdle, profile=prof)
    return {"file": path, "opportunity": opp, "profile": prof, "profile_source": psrc, **res,
            "best": res["ranked"][0]["strategy"] if res["ranked"] else None,
            "status": "ok" if res["ranked"] else "insufficient"}


def cmd_strategy_evaluate(ctx, a):
    return _strategy_eval(ctx, a.file, a.assumptions, a.profile, a.strategies, a.hurdle)


def cmd_strategy_allocate(ctx, a):
    from vnrealty.strategy.allocate import allocate
    d = load_json(a.file, "candidates")
    cands, existing = (d, None) if isinstance(d, list) else (d.get("candidates", []), d.get("existing"))
    prof, psrc = C.load_profile(a.profile, ctx.data_dir)
    r = allocate(cands, _num(a.cash), prof, existing=existing, reserve=_num(a.reserve))
    return {"profile_source": psrc, "result": r, "status": _status(r)}


def _sens_subject(ctx, a):
    """(subject, base_assumptions): a Deal file, or an opportunity file + --strategy NAME."""
    if a.strategy:
        from vnrealty.strategy.catalog import build
        opp, ass = _opportunity(a.file, None)
        return (lambda x: build(a.strategy, opp, x)), ass
    raw, d = C.load_deal(a.file)
    if isinstance(d, Insufficient):
        raise CliError(f"{a.file}: {d.reason}")
    return d, None


def cmd_strategy_tornado(ctx, a):
    from vnrealty.strategy.sensitivity import tornado
    subj, base = _sens_subject(ctx, a)
    if a.ranges:
        ranges = {k: tuple(v) for k, v in load_json(a.ranges, "ranges").items()}
        basis = "given"
    else:
        src = dataclasses.asdict(subj) if not callable(subj) or dataclasses.is_dataclass(subj) else base
        keys = ("price", "rent", "price_growth", "float_rate", "vacancy", "value_after", "build_cost",
                "after_repair_value", "master_rent", "rent_growth")
        ranges = {k: (src[k] * (1 - a.swing), src[k] * (1 + a.swing)) for k in keys
                  if isinstance(src.get(k), (int, float)) and src.get(k)}
        basis = f"default ±{a.swing:.0%} swing around base (judgement; pass --ranges to set real ends)"
    r = tornado(subj, base, ranges)
    return {"ranges_basis": basis, "result": r, "status": _status(r)}


def cmd_strategy_break_even(ctx, a):
    from vnrealty.strategy.sensitivity import break_even
    subj, base = _sens_subject(ctx, a)
    r = break_even(subj, a.field, target=a.target, value=a.value, lo=a.lo, hi=a.hi, base_assumptions=base)
    return {"result": r, "status": _status(r)}


def cmd_strategy_profile(ctx, a):
    from vnrealty.strategy.profile import QUESTIONS, profile_constraints, profile_from_answers
    if a.action == "questions":
        return {"questions": QUESTIONS}
    if a.action == "from-answers":
        if not a.file:
            raise CliError("usage: strategy profile from-answers ANSWERS.json")
        ans = load_json(a.file, "answers")
        prof = profile_from_answers(ans.get("answers", ans))
        out = {"profile": prof, "constraints": profile_constraints(prof)}
        if not a.no_save:
            p = Path(a.out) if a.out else ctx.data_dir / "portfolio" / "profile.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(jsonable(prof), ensure_ascii=False, indent=1), encoding="utf-8")
            out["saved"] = str(p)
        return out
    prof, src = C.load_profile(a.file, ctx.data_dir)
    return {"profile": prof, "source": src, "constraints": profile_constraints(prof)}


# =================================================================== plan / finplan

def _lot(ctx, path: str):
    from vnrealty.plan.options import Lot
    d = load_json(path, "lot")
    names = {f.name for f in dataclasses.fields(Lot)}
    value_src = "file"
    if d.get("value") is None and d.get("subject"):
        s = resolve_subject(ctx.con, d["subject"], ctx.as_of)
        v = C.run_value(ctx.con, s, ctx.as_of, record=False)
        if isinstance(v["combined"], Insufficient):
            raise CliError(f"lot value: {v['combined'].reason}")
        d["value"] = v["combined"].value
        d.setdefault("area_m2", s.get("area_m2"))
        value_src = f"value {d['subject']} (triangulated)"
    missing = [k for k in ("value", "area_m2") if d.get(k) is None]
    if missing:
        raise CliError(f"lot needs {missing} (or a 'subject' to value)")
    return Lot(**{k: v for k, v in d.items() if k in names}), value_src, d


def cmd_plan(ctx, a):
    from vnrealty.plan.options import evaluate
    lot, src, raw = _lot(ctx, a.file)
    r = evaluate(lot)
    return {"file": a.file, "lot": lot, "value_source": src, **r,
            "status": "ok" if r.get("ranking") else "insufficient"}


def cmd_finplan(ctx, a):
    from vnrealty.plan.finplan import affordability, purchase_plan
    h, src = C.load_household(a.household, ctx.data_dir)
    if a.action == "ladder":
        if not a.file:
            raise CliError("usage: finplan ladder DEAL.json --years N")
        raw, d = C.load_deal(a.file)
        if isinstance(d, Insufficient):
            return {"status": "insufficient", "deal": d}
        r = purchase_plan(h, d, a.years, start=a.start or ctx.as_of[:7])
        return {"household_source": src, "deal_file": a.file, "years": a.years, "plan": r, "status": _status(r)}
    deal = None
    if a.deal:
        raw, deal = C.load_deal(a.deal)
        if isinstance(deal, Insufficient):
            return {"status": "insufficient", "deal": deal}
    r = affordability(h, deal)
    return {"household_source": src, "affordability": r, "status": _status(r)}


# =================================================================== portfolio

_UNIT_FLAGS = {"ptype": "ptype", "ward": "ward_code", "address": "address", "lat": "lat", "lng": "lng",
               "area": "area_m2", "bought_at": "bought_at", "cost": "cost", "share": "share", "loan": "loan",
               "loan_rate": "loan_rate", "loan_term": "loan_term_years", "value": "value", "value_at": "value_at",
               "legal": "legal", "status": "status", "listing": "listing_id", "notes": "notes", "name": "name"}
_MONEY_FLAGS = {"cost", "loan", "value"}


def _unit_fields(ctx, a) -> dict:
    out = {}
    for flag, col in _UNIT_FLAGS.items():
        v = getattr(a, flag, None)
        if v is None:
            continue
        if flag in _MONEY_FLAGS:
            v = _num(v)
        if flag == "ward":
            v = _ward(ctx, v)
        if flag == "listing":
            v = int(str(v).split(":")[-1])
        out[col] = v
    return out


def cmd_unit_add(ctx, a):
    from vnrealty.portfolio.units import add_unit
    f = _unit_fields(ctx, a)
    f.pop("name", None)
    return {"id": add_unit(ctx.con, a.id, a.unit_name, **f)}


def cmd_unit_list(ctx, a):
    from vnrealty.portfolio.units import list_units
    return {"units": list_units(ctx.con, a.status)}


def cmd_unit_update(ctx, a):
    from vnrealty.portfolio.units import update_unit
    f = _unit_fields(ctx, a)
    if not f:
        raise CliError("nothing to update")
    try:
        update_unit(ctx.con, a.id, **f)
    except KeyError:
        raise CliError(f"no unit {a.id}")
    return {"id": a.id, "updated": sorted(f)}


def cmd_lease_add(ctx, a):
    from vnrealty.portfolio.units import add_lease
    f = {k: v for k, v in {"tenant": a.tenant, "end": a.end, "deposit": _num(a.deposit), "due_day": a.due_day,
                           "notes": a.notes}.items() if v is not None}
    return {"id": add_lease(ctx.con, a.unit.split(":")[-1], a.start, _num(a.rent), **f)}


def cmd_lease_end(ctx, a):
    from vnrealty.portfolio.units import end_lease
    end_lease(ctx.con, a.id, a.end or ctx.as_of, a.status)
    return {"id": a.id, "end": a.end or ctx.as_of, "status_set": a.status}


def cmd_txn_add(ctx, a):
    from vnrealty.portfolio.units import add_txn
    unit = None if a.unit in ("-", "none") else a.unit.split(":")[-1]
    tid = add_txn(ctx.con, a.at or ctx.as_of, _num(a.amount), a.category, unit_id=unit, lease_id=a.lease,
                  period=a.period, memo=a.memo)
    return {"id": tid}


def cmd_portfolio(ctx, a):
    from vnrealty.portfolio.ops import monthly_close
    from vnrealty.portfolio.units import occupancy, rent_roll, summary
    if a.action:
        if a.action[0] != "close" or len(a.action) != 2:
            raise CliError("usage: portfolio [close YYYY-MM]")
        return monthly_close(ctx.con, a.action[1], as_of=ctx.as_of if ctx.as_of_explicit else None)
    return {**summary(ctx.con, ctx.as_of), "occupancy": occupancy(ctx.con, ctx.as_of),
            "rent_roll": rent_roll(ctx.con, ctx.as_of)}


def cmd_risk(ctx, a):
    from vnrealty.portfolio.risk import risk_report
    return risk_report(ctx.con, ctx.as_of, _num(a.cash), ltv_limit=a.ltv_limit, dscr_min=a.dscr_min,
                       liquidity_min=a.liquidity_min, fixed_costs_month=_num(a.fixed_costs))


def cmd_ledger_open(ctx, a):
    from vnrealty.portfolio.ledger import open_paper_deal
    spec = load_json(a.spec, "spec") if a.spec else None
    did = open_paper_deal(ctx.con, subject_key(a.subject), a.action, _num(a.price), _num(a.est_value), spec=spec,
                          verdict=a.verdict, opened_at=ctx.as_of)
    return {"id": did, "subject": subject_key(a.subject), "action": a.action}


def cmd_ledger_close(ctx, a):
    from vnrealty.portfolio.ledger import close
    close(ctx.con, a.id, load_json(a.outcome, "outcome"), closed_at=ctx.as_of, review=a.review)
    return {"id": a.id, "closed_at": ctx.as_of}


def cmd_ledger_list(ctx, a):
    from vnrealty.portfolio.ledger import list_deals
    return {"deals": list_deals(ctx.con, open_only=a.open)}


def cmd_ledger_scorecard(ctx, a):
    from vnrealty.portfolio.ledger import scorecard
    return scorecard(ctx.con)


# =================================================================== legal

def _subject_ptype(ctx, text: str, ptype: str | None) -> tuple[str, str]:
    if ptype:
        return subject_key(text), ptype
    s = resolve_subject(ctx.con, text, ctx.as_of)
    if not s.get("ptype"):
        raise CliError("subject has no ptype: pass --ptype")
    return s["subject"], s["ptype"]


def cmd_legal_checklist(ctx, a):
    from vnrealty.legal.checklist import status
    key, ptype = _subject_ptype(ctx, a.subject, a.ptype)
    return {"subject": key, "ptype": ptype, **status(ctx.con, key, ptype, foreign=a.foreign)}


def cmd_legal_set(ctx, a):
    from vnrealty.legal.checklist import set_status
    jid = set_status(ctx.con, subject_key(a.subject), a.item, a.status, note=a.note, at=ctx.as_of)
    return {"subject": subject_key(a.subject), "item": a.item, "status_set": a.status, "journal_id": jid}


def cmd_legal_costs(ctx, a):
    from vnrealty.legal.checklist import transaction_costs
    t = str(a.price)
    if t.startswith(("listing:", "unit:")) or t.endswith(".json"):
        s = resolve_subject(ctx.con, t, ctx.as_of)
        price = s.get("ask") or s.get("cost")
        if price is None:
            raise CliError(f"{t} has no price")
    else:
        price = _num(t)
    r = transaction_costs(price, official_value=_num(a.official), role=a.role, new_build=a.new_build,
                          broker_rate=a.broker_rate, land_use_fee=_num(a.land_use_fee))
    return {"price": price, **r}


# =================================================================== calibrate / score / screen / price

def cmd_calibrate(ctx, a):
    from vnrealty.valuation.calibrate import score
    from vnrealty.valuation.triangulate import method_weights
    sc = score(ctx.con, ctx.as_of)
    return {"methods": sc, "weights": method_weights(ctx.con, ctx.as_of),
            "status": "ok" if sc else "insufficient",
            **({} if sc else {"reason": "no valuation has later evidence to grade against yet"})}


def _score_components(ctx, s: dict, deal_file: str | None) -> dict:
    from vnrealty.legal.checklist import status as legal_status
    from vnrealty.market.landscape import days_on_market
    from vnrealty.market.rent import gross_yield
    comps: dict = {}
    notes: dict = {}
    v = C.run_value(ctx.con, s, ctx.as_of, record=False)
    if isinstance(v["combined"], Estimate) and s.get("ask"):
        c = v["combined"]
        comps["value_gap"] = {"estimate": c.value, "ask": s["ask"], "lo": c.lo, "hi": c.hi}
    else:
        notes["value_gap"] = "no triangulated value" if not isinstance(v["combined"], Estimate) else "no asking price"
    if deal_file:
        from vnrealty.deal.engine import analyse
        from vnrealty.deal.ev import default_scenarios, ev
        raw, d = C.load_deal(deal_file)
        if isinstance(d, Insufficient):
            notes["irr"] = d.reason
        else:
            m = analyse(d)
            comps["irr"] = {"irr": m["irr"], "hurdle": d.hurdle}
            comps["ev"] = {"p_loss": ev(d, raw.get("scenarios") or default_scenarios(d))["p_loss"]}
            gy = gross_yield(ctx.con, s.get("ward_code"), s.get("ptype"), ctx.as_of)
            if not isinstance(gy, Insufficient) and m["yield_gross"]:
                comps["yield"] = {"yield": m["yield_gross"], "ward_median": gy["yield"]}
            else:
                notes["yield"] = gy.reason if isinstance(gy, Insufficient) else "deal has no rent"
            comps["risk"] = {"flags": [{"code": r, "severity": "high" if r in ("dscr", "cash") else "medium"}
                                       for r in m["reasons"]]}
    else:
        notes["irr"] = "no deal file (--deal): IRR is a core component, so the grade is withheld"
    if s.get("ptype"):
        comps["legal"] = {"status": legal_status(ctx.con, s["subject"], s["ptype"])["overall"]}
    dom = days_on_market(ctx.con, ctx.as_of, s.get("ward_code"), s.get("ptype"))
    if not isinstance(dom, Insufficient):
        comps["liquidity"] = {"days_to_sell": dom["median_completed"]}
    else:
        notes["liquidity"] = dom.reason
    return {"components": comps, "notes": notes, "value": v}


def cmd_score(ctx, a):
    from vnrealty.score import grade
    s = resolve_subject(ctx.con, a.subject, ctx.as_of)
    sc = _score_components(ctx, s, a.deal)
    g = grade(sc["components"])
    return {"subject": s["subject"], "grade": g, "components": sc["components"], "not_available": sc["notes"],
            "status": "ok" if g["status"] == "graded" else "insufficient"}


def _screen_undervalued(ctx, rows, threshold, ward=None):
    """Log residual of each listing against a hedonic model fitted per property type (and ward when given)."""
    from vnrealty.valuation.hedonic import residual
    models, hits, fails = {}, [], {}
    for r in rows:
        pt = r["ptype"]
        if pt not in models:
            models[pt] = C.fit_hedonic(ctx.con, ctx.as_of, pt, ward)
        model = models[pt]
        if isinstance(model, Insufficient):
            fails[pt] = model.reason
            continue
        e = residual(model, r)
        if isinstance(e, Insufficient) or e > threshold:
            continue
        hits.append({**_hit(r), "rule": "undervalued", "residual_log": e,
                     "why": f"asking price/m² {math.exp(e) - 1:+.0%} vs the hedonic model's price (log residual {e:+.2f}; model {model.detail.get('cli_filters') or 'pooled'}, n={model.n}, r²={model.r2:.2f})"})
    if not hits and fails and len(fails) == len(models):
        return Insufficient("undervalued", "; ".join(f"{k}: {v}" for k, v in fails.items()))
    return sorted(hits, key=lambda h: h["residual_log"])


def _screen_yield(ctx, rows, margin):
    from vnrealty.market.rent import gross_yield, rent_ppm2
    hits, cache = [], {}
    for r in rows:
        k = (r["ward_code"], r["ptype"])
        if k not in cache:
            cache[k] = (rent_ppm2(ctx.con, *k, ctx.as_of), gross_yield(ctx.con, *k, ctx.as_of))
        rent, gy = cache[k]
        if isinstance(rent, Insufficient) or isinstance(gy, Insufficient):
            continue
        if (rent.get("n") or 0) < YIELD_MIN_RENTS:   # a ward rent median from a handful of ads is noise, not a yield
            continue
        y = C.listing_yield(r, rent["median"])
        if y is None or y < gy["yield"] * (1 + margin):
            continue
        hits.append({**_hit(r), "rule": "yield", "yield": y, "ward_median_yield": gy["yield"],
                     "why": f"asking gross yield {y:.1%} vs ward/type median {gy['yield']:.1%} "
                            f"(ward rent n={rent['n']})"})
    return sorted(hits, key=lambda h: -h["yield"])


def _screen_catalyst(ctx, rows, km, min_p):
    from vnrealty.infra.catalog import catalysts_for
    from vnrealty.projection.catalysts import effective_uplift
    hits = []
    for r in rows:
        if r.get("lat") is None or r.get("lng") is None:
            continue
        cs = [c for c in catalysts_for(ctx.con, r["lat"], r["lng"], km)["catalysts"] if c["p"] >= min_p]
        if not cs:
            continue
        best = max(cs, key=lambda c: effective_uplift(c) * c["p"])
        hits.append({**_hit(r), "rule": "catalyst", "catalyst": best["id"], "distance_km": best["distance_km"],
                     "p": best["p"], "uplift_effective": effective_uplift(best), "year": best["year"],
                     "why": f"{best.get('name') or best['id']} {best['distance_km']:.1f} km away, chance {best['p']:.0%},"
                            f" done {best['year']}"})
    return sorted(hits, key=lambda h: -(h["p"] * h["uplift_effective"]))


def _screen_motivated(ctx, rows, days):
    from vnrealty.listings.track import changes
    ch = changes(ctx.con, C.days_before(ctx.as_of, days), ctx.as_of)
    by: dict = {}
    for c in ch.get("cuts", []):
        by.setdefault(c["listing_id"], []).append(c)
    idx = {r["id"]: r for r in rows}
    hits = []
    for lid, cs in by.items():
        if lid not in idx:
            continue
        tot = sum(c["vnd"] for c in cs)
        hits.append({**_hit(idx[lid]), "rule": "motivated", "n_cuts": len(cs), "cut_vnd": tot,
                     "cut_pcts": [c["pct"] for c in cs],
                     "why": f"{len(cs)} price cut(s) in {days} days"})
    return sorted(hits, key=lambda h: (-h["n_cuts"], h["cut_vnd"]))


def _hit(r: dict) -> dict:
    return {"listing_id": r["id"], "why": None, "ptype": r["ptype"], "ward_code": r["ward_code"], "price": r["price"],
            "area_m2": r["area_m2"], "price_m2": r["price_m2"], "legal": r["legal"], "alley_m": r["alley_m"],
            "seen_at": r["seen_at"], "title": r["title"]}


def _screen_pricing(ctx, a):
    from vnrealty.pricing.screen import rank_listings
    f = {"deal": "sale"}
    if a.ward:
        f["ward"] = _ward(ctx, a.ward)
    if a.ptype:
        f["ptypes"] = [p.strip() for p in a.ptype.split(",") if p.strip()]
    if a.max_price:
        f["max_price"] = _num(a.max_price)
    if a.min_price:
        f["min_price"] = _num(a.min_price)
    return rank_listings(ctx.con, ctx.as_of, filters=f, top=a.top)


def cmd_screen(ctx, a):
    rules = ["undervalued", "yield", "catalyst", "motivated"] if a.rule == "all" else [a.rule]
    out: dict = {"rule": a.rule, "results": {}, "insufficient": {}}
    if "pricing" in rules:
        r = _screen_pricing(ctx, a)
        out["results"]["pricing"] = r
        out["status"] = _status(r)
        return out
    rows = C.listing_rows(ctx.con, ctx.as_of, ward=_ward(ctx, a.ward), ptype=a.ptype, min_price=_num(a.min_price),
                          max_price=_num(a.max_price), since=C.days_before(ctx.as_of, a.window))
    out["universe"] = len(rows)
    for rule in rules:
        if rule == "undervalued":
            r = _screen_undervalued(ctx, rows, a.threshold, _ward(ctx, a.ward))
        elif rule == "yield":
            r = _screen_yield(ctx, rows, a.margin)
        elif rule == "catalyst":
            r = _screen_catalyst(ctx, rows, a.km, a.min_p)
        else:
            r = _screen_motivated(ctx, rows, a.window)
        if isinstance(r, Insufficient):
            out["insufficient"][rule] = r.reason
        else:
            out["results"][rule] = r[:a.top]
    merged: dict = {}
    for rule, hits in out["results"].items():
        for h in hits:
            m = merged.setdefault(h["listing_id"], {k: h[k] for k in ("listing_id", "ptype", "ward_code", "price",
                                                                        "area_m2", "legal", "alley_m", "title")})
            m.setdefault("rules", []).append(rule)
            m.setdefault("why", []).append(h["why"])
    out["hits"] = sorted(merged.values(), key=lambda m: -len(m["rules"]))[:a.top]
    out["caveat"] = ("cheap for a reason is not an opportunity: check legal status, title, kiệt width and planning "
                     "before analysis")
    out["status"] = "ok" if out["results"] else "insufficient"
    return out


YIELD_MIN_RENTS = 20   # rentals of the same ward and type needed before the yield screen trusts their median


def cmd_price(ctx, a):
    from vnrealty.pricing.metrics import evaluate, make_ctx
    from vnrealty.pricing.peers import snapshot
    from vnrealty.pricing.score import pricing_score
    s = resolve_subject(ctx.con, a.subject, ctx.as_of)
    if s.get("listing_id") is not None:
        listing = snapshot(ctx.con, int(s["listing_id"]), ctx.as_of)
        if isinstance(listing, Insufficient):
            return {"subject": s["subject"], "status": "insufficient", "pricing": listing}
    else:
        listing = {k: v for k, v in s.items()}
        listing.setdefault("price", s.get("ask"))
    kw = dict(load_json(a.ctx, "ctx") or {}) if a.ctx else {}
    if a.with_value:
        v = C.run_value(ctx.con, s, ctx.as_of, record=False)["combined"]
        if isinstance(v, Estimate):
            kw.setdefault("valuation", v)
    if "hedonic" not in kw:   # the same pooled model the screen fits, so `price` and `screen` give one score
        from vnrealty.valuation import hedonic as _hed
        _m = _hed.fit(ctx.con, ctx.as_of)
        if not isinstance(_m, Insufficient):
            kw["hedonic"] = _m
    mctx = make_ctx(ctx.con, ctx.as_of, **kw)
    metrics = evaluate(listing, mctx)
    ptype = "rent" if listing.get("deal") == "rent" else (listing.get("ptype") or "other")
    sc = pricing_score(metrics, ptype)
    return {"subject": s["subject"], "ptype": ptype, "price": listing.get("price"), "metrics": metrics,
            "score": sc, "legal": listing.get("legal"),
            "status": "ok" if sc.get("score") is not None else "insufficient"}


# =================================================================== series / forecast

def cmd_series_list(ctx, a):
    rows = store.rows(ctx.con, "SELECT source, scope_kind, scope, ptype, kind, unit, COUNT(DISTINCT month) AS months, "
                               "MIN(month) AS first_month, MAX(month) AS last_month, COUNT(DISTINCT seen_at) AS vintages "
                               "FROM price_series WHERE seen_at <= ? GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY 2, 3, 4, 1",
                      (_end(ctx.as_of),))
    return {"series": rows, "min_months_to_backtest": 24}


def cmd_series_add(ctx, a):
    add_points = guarded("vnrealty.forecast.series", "add_points")
    pts = load_json(a.points, "points")
    n = add_points(ctx.con, a.source, a.scope_kind, a.scope, a.ptype, [tuple(p) for p in pts], a.unit, a.url,
                   a.seen_at or ctx.as_of, kind=a.kind, notes=a.notes)
    return {"inserted": n, "source": a.source, "scope": a.scope, "ptype": a.ptype}


def cmd_series_ingest(ctx, a):
    ing = guarded("vnrealty.forecast.series", "ingest_capture")
    p = Path(a.path)
    files = sorted(x for x in p.rglob("*.json")) if p.is_dir() else [p]
    out = []
    for f in files:
        obj = load_json(str(f), "capture")
        r = ing(ctx.con, obj, a.scope_kind, a.scope, a.ptype, item=a.item, unit=a.unit, multiplier=a.multiplier)
        out.append({"file": str(f), "result": r})
    bad = [o for o in out if isinstance(o["result"], Insufficient)]
    return {"files": out, "status": "insufficient" if out and len(bad) == len(out) else "ok"}


def _area_forecast(ctx, scope_kind, scope, ptype, months_ahead):
    get_series = guarded("vnrealty.forecast.series", "get_series")
    splice = guarded("vnrealty.forecast.series", "splice")
    default_models = guarded("vnrealty.forecast.models", "default_models")
    walk_forward = guarded("vnrealty.forecast.backtest", "walk_forward")
    ensemble_weights = guarded("vnrealty.forecast.backtest", "ensemble_weights")
    fan = guarded("vnrealty.forecast.fan", "fan")
    ss = get_series(ctx.con, scope_kind, scope, ptype, as_of=ctx.as_of)
    if not ss:
        return {"status": "insufficient", "reason": f"no price series for {scope_kind}/{scope}/{ptype}"}
    sp = splice(list(ss.values()))
    models = default_models()
    bt = walk_forward(sp["points"], models, as_of=ctx.as_of)
    out = {"scope_kind": scope_kind, "scope": scope, "ptype": ptype, "sources": sorted(ss), "splice": sp,
           "backtest": bt}
    if isinstance(bt, Insufficient):
        months_needed = guarded("vnrealty.forecast.backtest", "months_needed")
        out["months_have"] = len(sp["points"])
        out["months_needed"] = months_needed(24, (3, 6, 12, 24))
        out["status"] = "insufficient"
        out["reason"] = bt.reason
        return out
    out["weights"] = {h: ensemble_weights(bt, h) for h in (3, 6, 12, 24)}
    out["fan"] = fan(sp["points"], models, None, months_ahead, results=bt, as_of=ctx.as_of)
    out["status"] = _status(out["fan"])
    return out


def _local_catalysts(ctx, s: dict, km: float) -> list[dict]:
    """catalysts_for plus each project's ``local`` / ``area_uplift`` judgement from project.notes (catalysts_for does
    not carry them yet); project_asset then overlays only the local ones."""
    from vnrealty.infra.catalog import catalysts_for, near
    if s.get("lat") is None or s.get("lng") is None:
        return []
    notes = {r["id"]: r.get("notes") or {} for r in near(ctx.con, s["lat"], s["lng"], km)}
    out = []
    for c in catalysts_for(ctx.con, s["lat"], s["lng"], km)["catalysts"]:
        n = notes.get(c["id"]) or {}
        out.append({**c, "local": bool(n.get("local", c.get("local", False))),
                    "area_uplift": n.get("area_uplift", c.get("area_uplift"))})
    return out


def cmd_forecast(ctx, a):
    if a.action == "grade":
        grade = guarded("vnrealty.forecast.record", "grade")
        return grade(ctx.con, ctx.as_of)
    if a.action == "series":
        if len(a.args) < 1:
            raise CliError("usage: forecast series SCOPE [PTYPE]")
        scope = a.args[0]
        ptype = a.args[1] if len(a.args) > 1 else None
        kind = a.scope_kind or ("city" if scope in ("city", "da-nang") else "ward")
        scope = "da-nang" if scope == "city" else scope
        out = _area_forecast(ctx, kind, scope, ptype, a.months)
        if out.get("status") == "ok" and not a.no_record:
            rec = guarded("vnrealty.forecast.record", "record")
            subj = guarded("vnrealty.forecast.series", "subject_for")("splice", kind, scope, ptype)
            out["recorded"] = rec(ctx.con, subj, ctx.as_of, "ensemble", jsonable(out["fan"]))
        return out
    if a.action == "asset":
        if not a.args:
            raise CliError("usage: forecast asset SUBJECT --years N")
        project_asset = guarded("vnrealty.forecast.asset", "project_asset")
        sell_timing = guarded("vnrealty.forecast.asset", "sell_timing")
        s = resolve_subject(ctx.con, a.args[0], ctx.as_of)
        v = C.run_value(ctx.con, s, ctx.as_of, record=False)
        scope_kind, scope = ("ward", s["ward_code"]) if s.get("ward_code") and a.scope_kind != "city" \
            else ("city", "da-nang")
        area = _area_forecast(ctx, scope_kind, scope, s.get("ptype"), a.years * 12 + 12)
        if area.get("status") != "ok" and scope_kind == "ward":
            area = _area_forecast(ctx, "city", "da-nang", s.get("ptype"), a.years * 12 + 12)
        fan = area.get("fan") or Insufficient("fan", area.get("reason") or "area fan unavailable")
        cats = _local_catalysts(ctx, s, a.km)
        proj = project_asset(v["combined"], fan, cats, a.years, ctx.as_of[:7])
        out = {"subject": s["subject"], "value": v["combined"], "area": {k: area.get(k) for k in
                                                                        ("scope_kind", "scope", "status", "reason")},
               "projection": proj}
        if a.deposit_rate is not None and not isinstance(proj, Insufficient):
            out["sell_timing"] = sell_timing(proj, C.sell_costs(), a.deposit_rate, a.holding_cost,
                                             float(s.get("share") or 1.0))
        elif a.deposit_rate is None:
            out["sell_timing"] = Insufficient("sell_timing", "pass --deposit-rate")
        if not isinstance(proj, Insufficient) and not a.no_record:
            rec = guarded("vnrealty.forecast.record", "record")
            out["recorded"] = rec(ctx.con, s["subject"], ctx.as_of, "asset", jsonable(proj))
        out["status"] = _status(proj)
        return out
    raise CliError("usage: forecast series SCOPE PTYPE | asset SUBJECT --years N | grade")


# =================================================================== reports / journal

def cmd_report(ctx, a):
    from vnrealty.report import builders as B
    from vnrealty.report.html import write_report
    kind, subj = a.kind, a.subject
    if kind == "market":
        target = subj or "city"
        w = _ward(ctx, target if target != "city" else None)
        payload = {"market": _market_read(ctx, w, a.ptype, "sale"), "yields": _yields(ctx, w, a.ptype)}
    elif kind == "listing":
        if not subj:
            raise CliError("report listing SUBJECT")
        s = resolve_subject(ctx.con, subj, ctx.as_of)
        payload = {"value": C.run_value(ctx.con, s, ctx.as_of, record=False)}
        from vnrealty.valuation.comps import adjust, load_params, select_comps
        payload["comps"] = [adjust(c, s, load_params()) for c in select_comps(ctx.con, s, ctx.as_of)]
        payload["score"] = cmd_score(ctx, argparse.Namespace(subject=subj, deal=a.deal))
        if s.get("lat") is not None and s.get("lng") is not None:
            from vnrealty.infra.catalog import near
            payload["projects"] = near(ctx.con, s["lat"], s["lng"], 3.0)
        if s.get("listing_id"):
            from vnrealty.listings.track import history
            payload["history"] = history(ctx.con, int(s["listing_id"]))
    elif kind == "deal":
        raw, d = C.load_deal(subj)
        if isinstance(d, Insufficient):
            return {"status": "insufficient", "deal": d}
        payload = {"file": subj, **_deal_payload(d), **_ev_payload(raw, d, None, None)}
    elif kind == "compare":
        items = [subj] + (a.more or [])
        payload = cmd_compare(ctx, argparse.Namespace(subjects=items, deal=a.deal))
    elif kind == "portfolio":
        payload = {"portfolio": cmd_portfolio(ctx, argparse.Namespace(action=None))}
        if a.cash is not None:
            payload["risk"] = cmd_risk(ctx, argparse.Namespace(cash=a.cash, ltv_limit=0.6, dscr_min=1.2,
                                                                liquidity_min=6.0, fixed_costs=None))
        if subj:
            from vnrealty.portfolio.ops import monthly_close
            payload["close"] = monthly_close(ctx.con, subj)
    elif kind == "plan":
        payload = cmd_plan(ctx, argparse.Namespace(file=subj))
    elif kind == "screen":
        ns = argparse.Namespace(rule=subj or "all", ward=a.ward, ptype=a.ptype, min_price=None, max_price=None,
                                window=180, threshold=-0.10, margin=0.0, km=3.0, min_p=0.3, top=20)
        payload = cmd_screen(ctx, ns)
    elif kind == "strategy":
        payload = _strategy_eval(ctx, subj, None, a.profile)
    else:
        raise CliError(f"unknown report kind {kind!r}")
    rep = getattr(B, kind)(jsonable(payload), as_of=ctx.as_of)
    out_dir = Path(a.out) if a.out else ctx.data_dir / "reports"
    paths = write_report(rep, kind, Path(str(subj or kind)).stem.replace(":", "-"), out_dir=out_dir)
    return {"kind": kind, "subject": subj, "paths": paths, "sections": len(rep["sections"])}


def cmd_journal_add(ctx, a):
    cur = ctx.con.execute("INSERT INTO journal(at, kind, subject, body) VALUES (?, ?, ?, ?)",
                          (now_ts() if not ctx.as_of_explicit else ctx.as_of, a.kind,
                           subject_key(a.subject) if a.subject else None, a.text))
    ctx.con.commit()
    return {"id": cur.lastrowid, "kind": a.kind}


def cmd_journal_list(ctx, a):
    q, args = "SELECT * FROM journal WHERE at <= ?", [_end(ctx.as_of)]
    if a.kind:
        q += " AND kind = ?"
        args.append(a.kind)
    return {"entries": store.rows(ctx.con, q + " ORDER BY at DESC, id DESC LIMIT ?", (*args, a.limit))}


# =================================================================== parser

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError(f"{self.prog}: {message}")


def _globals(p, suppress: bool):
    d = argparse.SUPPRESS
    p.add_argument("--db", default=d if suppress else str(store.default_path()), help="SQLite file (default data/vnr.sqlite)")
    p.add_argument("--as-of", dest="as_of", default=d if suppress else None, help="YYYY-MM-DD (default today)")
    p.add_argument("--json", action="store_true", default=d if suppress else False, help="machine output")


def build_parser() -> argparse.ArgumentParser:
    G = _Parser(add_help=False)
    _globals(G, True)
    top = _Parser(prog="vnr", description="vnrealty — the real-estate desk (Đà Nẵng). Numbers from libraries only.")
    _globals(top, False)
    sp = top.add_subparsers(dest="cmd", parser_class=_Parser)

    def group(parent_sp, name, help_=None):
        g = parent_sp.add_parser(name, help=help_, parents=[G])
        return g, g.add_subparsers(dest=f"{name}_cmd", parser_class=_Parser)

    def cmd(parent_sp, name, func, help_=None):
        c = parent_sp.add_parser(name, help=help_, parents=[G])
        c.set_defaults(func=func)
        return c

    # browser / capture / ingest
    _, b = group(sp, "browser", "injectable extractors")
    cmd(b, "list", cmd_browser_list)
    cmd(b, "script", cmd_browser_script).add_argument("name")
    _, c = group(sp, "capture", "save a browser capture under data/raw/")
    x = cmd(c, "save", cmd_capture_save)
    x.add_argument("file", nargs="?")
    x.add_argument("--text")
    x.add_argument("--url")
    x.add_argument("--site")
    x.add_argument("--kind")
    x.add_argument("--deal")
    x.add_argument("--search")
    x.add_argument("--seen-at", dest="seen_at")
    cmd(sp, "ingest", cmd_ingest, "parse and store captures").add_argument("path")

    x = cmd(sp, "listings", cmd_listings, "listings with their latest price")
    x.add_argument("action", nargs="*")
    x.add_argument("--ward")
    x.add_argument("--ptype")
    x.add_argument("--deal", default="sale", choices=["sale", "rent"])
    x.add_argument("--min-price", dest="min_price")
    x.add_argument("--max-price", dest="max_price")
    x.add_argument("--watched", action="store_true")
    x.add_argument("--off", action="store_true")
    x.add_argument("--limit", type=int, default=50)

    _, s = group(sp, "search", "saved searches")
    x = cmd(s, "add", cmd_search_add)
    x.add_argument("name")
    x.add_argument("site")
    x.add_argument("url")
    x.add_argument("--criteria")
    cmd(s, "list", cmd_search_list)
    x = cmd(s, "touch", cmd_search_touch)
    x.add_argument("name")
    x.add_argument("--at")

    x = cmd(sp, "track", cmd_track, "what moved")
    x.add_argument("action", nargs="?")
    x.add_argument("--since")
    x.add_argument("--days", type=int, default=30)
    x = cmd(sp, "coverage", cmd_coverage, "listings/observations per ward, type, month")
    x.add_argument("--ward")

    _, w = group(sp, "wards")
    cmd(w, "seed", cmd_wards_seed)
    cmd(w, "match", cmd_wards_match).add_argument("text")

    x = cmd(sp, "market", cmd_market, "WARD|city, or yields | rents | index")
    x.add_argument("target", nargs="?", default="city")
    x.add_argument("--ward")
    x.add_argument("--ptype")
    x.add_argument("--deal", default="sale", choices=["sale", "rent"])
    x.add_argument("--save", action="store_true")

    _, s = group(sp, "sale", "sale evidence (ground truth)")
    x = cmd(s, "add", cmd_sale_add)
    x.add_argument("--price", required=True)
    x.add_argument("--sold-at", dest="sold_at", required=True)
    x.add_argument("--source", required=True)
    x.add_argument("--listing")
    x.add_argument("--ward")
    x.add_argument("--ptype")
    x.add_argument("--area", type=float)
    x.add_argument("--url")
    x.add_argument("--confidence", default="strong", choices=["strong", "medium", "weak"])
    x.add_argument("--notes")
    x = cmd(s, "list", cmd_sale_list)
    x.add_argument("--ward")
    x.add_argument("--listing")

    x = cmd(sp, "value", cmd_value, "triangulated value (recorded for calibration)")
    x.add_argument("subject")
    x.add_argument("--no-record", dest="no_record", action="store_true")
    x = cmd(sp, "comps", cmd_comps, "comparables with adjustments")
    x.add_argument("subject")
    x.add_argument("--km", type=float)
    x.add_argument("--months", type=int, default=12)
    x = cmd(sp, "history", cmd_history, "reconstructed price history")
    x.add_argument("subject")
    x.add_argument("--index", choices=["ward", "city"], default="ward")

    _, i = group(sp, "infra", "projects, catalysts, zoning")
    cmd(i, "seed", cmd_infra_seed)
    x = cmd(i, "near", cmd_infra_near)
    x.add_argument("latlng")
    x.add_argument("--km", type=float, default=3.0)
    x = cmd(i, "catalysts", cmd_infra_catalysts)
    x.add_argument("subject")
    x.add_argument("--km", type=float, default=3.0)
    x = cmd(i, "add", cmd_infra_add)
    x.add_argument("--file")
    x.add_argument("--id")
    x.add_argument("--name-vi", dest="name_vi")
    x.add_argument("--name-en", dest="name_en")
    x.add_argument("--kind")
    x.add_argument("--status")
    x.add_argument("--lat", type=float)
    x.add_argument("--lng", type=float)
    x.add_argument("--radius-km", dest="radius_km", type=float)
    x.add_argument("--wards")
    x.add_argument("--budget", dest="budget_vnd", type=float)
    x.add_argument("--start-year", dest="start_year", type=int)
    x.add_argument("--done-year", dest="done_year", type=int)
    x.add_argument("--p-done", dest="p_done", type=float)
    x.add_argument("--uplift", type=float)
    x.add_argument("--basis")
    x.add_argument("--url")
    x.add_argument("--title")
    x.add_argument("--claim")
    x = cmd(i, "cite", cmd_infra_cite)
    x.add_argument("id")
    x.add_argument("url")
    x.add_argument("--claim")
    x.add_argument("--title")
    x.add_argument("--published")
    x = cmd(i, "zoning", cmd_infra_zoning)
    x.add_argument("action", choices=["add", "show"])
    x.add_argument("subject")
    x.add_argument("--code")
    x.add_argument("--plan")
    x.add_argument("--source")
    x.add_argument("--note")

    x = cmd(sp, "project", cmd_project, "catalyst paths + Monte Carlo + hold vs sell")
    x.add_argument("subject")
    x.add_argument("--years", type=int, default=5)
    x.add_argument("--drift", type=float)
    x.add_argument("--vol", type=float)
    x.add_argument("--deposit-rate", dest="deposit_rate", type=float)
    x.add_argument("--holding-cost", dest="holding_cost", type=float, default=0.0)
    x.add_argument("--km", type=float, default=3.0)
    x.add_argument("--n", type=int, default=2000)

    x = cmd(sp, "deal", cmd_deal, "FILE (analyse + stress + yearly) | preset NAME")
    x.add_argument("file")
    x.add_argument("name", nargs="?")
    x.add_argument("--out")
    x.add_argument("--subject")
    x = cmd(sp, "ev", cmd_ev, "scenario expected value + kill triggers")
    x.add_argument("file")
    x.add_argument("--scenarios")
    x.add_argument("--kill")
    x = cmd(sp, "compare", cmd_compare, "side by side")
    x.add_argument("subjects", nargs="+")
    x.add_argument("--deal", help="deal template applied to listing/unit subjects")

    _, st = group(sp, "strategy", "every way to profit; allocation; sensitivity")
    x = cmd(st, "evaluate", cmd_strategy_evaluate)
    x.add_argument("file")
    x.add_argument("--profile")
    x.add_argument("--assumptions")
    x.add_argument("--strategies")
    x.add_argument("--hurdle", type=float)
    x = cmd(st, "allocate", cmd_strategy_allocate)
    x.add_argument("file")
    x.add_argument("--cash", required=True)
    x.add_argument("--profile")
    x.add_argument("--reserve")
    x = cmd(st, "tornado", cmd_strategy_tornado)
    x.add_argument("file")
    x.add_argument("--strategy")
    x.add_argument("--ranges")
    x.add_argument("--swing", type=float, default=0.2)
    x = cmd(st, "break-even", cmd_strategy_break_even)
    x.add_argument("file")
    x.add_argument("field")
    x.add_argument("--strategy")
    x.add_argument("--target", default="irr", choices=["irr", "npv", "profit"])
    x.add_argument("--value", type=float)
    x.add_argument("--lo", type=float)
    x.add_argument("--hi", type=float)
    x = cmd(st, "profile", cmd_strategy_profile)
    x.add_argument("action", nargs="?", choices=["questions", "from-answers", "show"], default="show")
    x.add_argument("file", nargs="?")
    x.add_argument("--out")
    x.add_argument("--no-save", dest="no_save", action="store_true")

    cmd(sp, "plan", cmd_plan, "best use of an owned lot").add_argument("file")
    x = cmd(sp, "finplan", cmd_finplan, "affordability | ladder DEAL.json --years N")
    x.add_argument("action", nargs="?", choices=["ladder"])
    x.add_argument("file", nargs="?")
    x.add_argument("--household")
    x.add_argument("--deal")
    x.add_argument("--years", type=float, default=15)
    x.add_argument("--start")

    _, u = group(sp, "unit", "owned units")

    def unit_flags(p):
        for f in ("ptype", "ward", "address", "bought_at", "legal", "status", "notes", "value_at", "listing",
                  "cost", "loan", "value"):
            p.add_argument("--" + f.replace("_", "-"), dest=f)
        for f in ("lat", "lng", "area", "share", "loan_rate", "loan_term"):
            p.add_argument("--" + f.replace("_", "-"), dest=f, type=float)
    x = cmd(u, "add", cmd_unit_add)
    x.add_argument("id")
    x.add_argument("unit_name", metavar="name")
    unit_flags(x)
    x = cmd(u, "list", cmd_unit_list)
    x.add_argument("--status")
    x = cmd(u, "update", cmd_unit_update)
    x.add_argument("id")
    x.add_argument("--name")
    unit_flags(x)

    _, l = group(sp, "lease", "leases")
    x = cmd(l, "add", cmd_lease_add)
    x.add_argument("unit")
    x.add_argument("--rent", required=True)
    x.add_argument("--start", required=True)
    x.add_argument("--tenant")
    x.add_argument("--end")
    x.add_argument("--deposit")
    x.add_argument("--due-day", dest="due_day", type=int)
    x.add_argument("--notes")
    x = cmd(l, "end", cmd_lease_end)
    x.add_argument("id", type=int)
    x.add_argument("--end")
    x.add_argument("--status", default="ended")

    _, t = group(sp, "txn", "money in/out")
    x = cmd(t, "add", cmd_txn_add)
    x.add_argument("unit")
    x.add_argument("amount")
    x.add_argument("category")
    x.add_argument("--at")
    x.add_argument("--lease", type=int)
    x.add_argument("--period")
    x.add_argument("--memo")

    cmd(sp, "portfolio", cmd_portfolio, "summary | close YYYY-MM").add_argument("action", nargs="*")
    x = cmd(sp, "risk", cmd_risk, "portfolio risk")
    x.add_argument("--cash", required=True)
    x.add_argument("--ltv-limit", dest="ltv_limit", type=float, default=0.6)
    x.add_argument("--dscr-min", dest="dscr_min", type=float, default=1.2)
    x.add_argument("--liquidity-min", dest="liquidity_min", type=float, default=6.0)
    x.add_argument("--fixed-costs", dest="fixed_costs")

    _, lg = group(sp, "ledger", "paper deals")
    x = cmd(lg, "open", cmd_ledger_open)
    x.add_argument("subject")
    x.add_argument("action", choices=["buy", "pass", "sell", "hold", "build"])
    x.add_argument("--price")
    x.add_argument("--est-value", dest="est_value")
    x.add_argument("--spec")
    x.add_argument("--verdict")
    x = cmd(lg, "close", cmd_ledger_close)
    x.add_argument("id", type=int)
    x.add_argument("--outcome", required=True)
    x.add_argument("--review")
    cmd(lg, "list", cmd_ledger_list).add_argument("--open", action="store_true")
    cmd(lg, "scorecard", cmd_ledger_scorecard)

    _, le = group(sp, "legal", "due diligence and costs")
    x = cmd(le, "checklist", cmd_legal_checklist)
    x.add_argument("subject")
    x.add_argument("--ptype")
    x.add_argument("--foreign", action="store_true")
    x = cmd(le, "set", cmd_legal_set)
    x.add_argument("subject")
    x.add_argument("item")
    x.add_argument("status", choices=["todo", "ok", "issue", "na"])
    x.add_argument("--note")
    x = cmd(le, "costs", cmd_legal_costs)
    x.add_argument("price")
    x.add_argument("--role", default="buyer", choices=["buyer", "seller"])
    x.add_argument("--official")
    x.add_argument("--new-build", dest="new_build", action="store_true")
    x.add_argument("--broker-rate", dest="broker_rate", type=float)
    x.add_argument("--land-use-fee", dest="land_use_fee")

    cmd(sp, "calibrate", cmd_calibrate, "grade past valuations, earn method weights")
    x = cmd(sp, "score", cmd_score, "graded verdict")
    x.add_argument("subject")
    x.add_argument("--deal")
    x = cmd(sp, "screen", cmd_screen, "opportunity screens")
    x.add_argument("--rule", default="all", choices=["pricing", "undervalued", "yield", "catalyst", "motivated", "all"])
    x.add_argument("--ward")
    x.add_argument("--ptype")
    x.add_argument("--min-price", dest="min_price")
    x.add_argument("--max-price", dest="max_price")
    x.add_argument("--top", type=int, default=20)
    x.add_argument("--window", type=int, default=180, help="days of listings / cuts considered")
    x.add_argument("--threshold", type=float, default=-0.10, help="undervalued: max log residual")
    x.add_argument("--margin", type=float, default=0.0, help="yield: min excess over the ward median (fraction)")
    x.add_argument("--km", type=float, default=3.0)
    x.add_argument("--min-p", dest="min_p", type=float, default=0.3)
    x = cmd(sp, "price", cmd_price, "relative-value pricing (vnrealty.pricing)")
    x.add_argument("subject")
    x.add_argument("--ctx", help="JSON of pricing.metrics.make_ctx keys (rent, adr, occupancy, rooms, road_width_m…)")
    x.add_argument("--with-value", dest="with_value", action="store_true",
                   help="pass today's triangulated value to the metrics")

    _, se = group(sp, "series", "area price series")
    cmd(se, "list", cmd_series_list)
    x = cmd(se, "add", cmd_series_add)
    x.add_argument("source")
    x.add_argument("scope")
    x.add_argument("ptype", nargs="?")
    x.add_argument("--points", required=True)
    x.add_argument("--url")
    x.add_argument("--scope-kind", dest="scope_kind", default="ward")
    x.add_argument("--unit", default="vnd_m2")
    x.add_argument("--kind", default="asking")
    x.add_argument("--seen-at", dest="seen_at")
    x.add_argument("--notes")
    x = cmd(se, "ingest", cmd_series_ingest)
    x.add_argument("path")
    x.add_argument("--scope", required=True)
    x.add_argument("--scope-kind", dest="scope_kind", default="ward")
    x.add_argument("--ptype")
    x.add_argument("--item", type=int, default=0)
    x.add_argument("--unit")
    x.add_argument("--multiplier", type=float)

    x = cmd(sp, "forecast", cmd_forecast, "series SCOPE PTYPE | asset SUBJECT | grade")
    x.add_argument("action", choices=["series", "asset", "grade"])
    x.add_argument("args", nargs="*")
    x.add_argument("--years", type=int, default=5)
    x.add_argument("--months", type=int, default=24)
    x.add_argument("--scope-kind", dest="scope_kind")
    x.add_argument("--deposit-rate", dest="deposit_rate", type=float)
    x.add_argument("--holding-cost", dest="holding_cost", type=float, default=0.0)
    x.add_argument("--km", type=float, default=3.0)
    x.add_argument("--no-record", dest="no_record", action="store_true")

    x = cmd(sp, "report", cmd_report, "write an HTML + Markdown report")
    x.add_argument("kind", choices=["market", "listing", "deal", "compare", "portfolio", "plan", "screen", "strategy"])
    x.add_argument("subject", nargs="?")
    x.add_argument("more", nargs="*")
    x.add_argument("--ptype")
    x.add_argument("--ward")
    x.add_argument("--deal")
    x.add_argument("--profile")
    x.add_argument("--cash")
    x.add_argument("--out")

    _, j = group(sp, "journal", "desk journal")
    x = cmd(j, "add", cmd_journal_add)
    x.add_argument("kind")
    x.add_argument("text")
    x.add_argument("--subject")
    x = cmd(j, "list", cmd_journal_list)
    x.add_argument("--kind")
    x.add_argument("--limit", type=int, default=50)
    return top


_CODES = {"ok": 0, "error": 1, "insufficient": 2, "unavailable": 2}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    want_json = "--json" in argv
    try:
        a = parser.parse_args(argv)
    except CliError as e:
        if want_json:
            print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
        else:
            print(f"error: {e}", file=sys.stderr)
        return 1
    if not getattr(a, "func", None):
        sub = getattr(a, f"{a.cmd}_cmd", None) if a.cmd else None
        if a.cmd and sub is None:
            try:
                parser.parse_args([a.cmd, "--help"])
            except SystemExit:
                return 1
        parser.print_help()
        return 1
    ctx = Ctx(a)
    name = " ".join(x for x in (a.cmd, getattr(a, f"{a.cmd}_cmd", None)) if x)
    try:
        out = a.func(ctx, a)
    except Unavailable as e:
        out = {"status": "unavailable", "reason": str(e)}
    except (CliError, ValueError, KeyError, TypeError, FileNotFoundError, sqlite3.Error) as e:
        out = {"status": "error", "error": f"{type(e).__name__}: {e}" if not isinstance(e, CliError) else str(e)}
    try:
        if isinstance(out, Raw):
            print(out)
            return 0
        payload = jsonable(out) if isinstance(out, dict) else {"result": jsonable(out)}
        status = payload.pop("status", None) or ("insufficient" if isinstance(out, Insufficient) else "ok")
        res = {"command": name, "as_of": ctx.as_of, "status": status, **payload}
        if ctx.json:
            print(json.dumps(res, ensure_ascii=False, default=str))
        else:
            if status == "error":
                print(f"error: {res.get('error')}", file=sys.stderr)
            else:
                print_human(res)
        return _CODES.get(status, 0)
    finally:
        ctx.close()


if __name__ == "__main__":
    sys.exit(main())
