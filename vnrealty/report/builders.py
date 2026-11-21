"""Report builders: one function per report kind, turning the CLI's JSON payload (library outputs, already plain
dicts) into the section list :func:`vnrealty.report.html.write_report` renders.

Every builder is ``f(payload: dict, as_of: str) -> {"title", "subtitle", "meta", "sections"}``. Nothing is computed
here except display formatting (report/fmt.py); a missing number is shown as missing, with its reason.
Section kinds follow the html.py docstring: kpis, table, chart, note, grade, cites, map.
"""
from __future__ import annotations

from .fmt import num, pct, signed, vnd

__all__ = ["market", "listing", "deal", "compare", "portfolio", "plan", "screen", "strategy", "LEGAL_FLAGS",
           "legal_flag"]

#: Title types that are flags in any report (parse.detect_legal codes).
LEGAL_FLAGS = {"so_chung": "shared certificate (sổ chung): sale needs the co-holders, hard to finance",
               "cho_so": "title pending (chờ sổ): the buyer carries the risk it never issues",
               "hdmb": "sale contract only (HĐMB): no certificate yet",
               "giay_tay": "handwritten title (giấy tay): not a transferable title"}


def legal_flag(code: str | None) -> str | None:
    """The flag text for a risky title code, else None."""
    return LEGAL_FLAGS.get(code or "")


def _meta(as_of: str, extra: str = "") -> str:
    return f"As of {as_of}. Asking prices are not sale prices. Decision support, not financial or legal advice." + \
        (f" {extra}" if extra else "")


def _insuf(x) -> str | None:
    if isinstance(x, dict) and (x.get("status") == "insufficient" or ("reason" in x and "method" in x
                                                                        and "value" not in x)):
        return x.get("reason") or "insufficient"
    return None


def _note(text: str, tone: str = "") -> dict:
    return {"kind": "note", "text": text, "tone": tone}


def _index_chart(idx, title: str) -> dict | None:
    if not isinstance(idx, dict) or not idx.get("months"):
        return None
    ms = [m for m in idx["months"] if m.get("index") is not None]
    if len(ms) < 2:
        return None
    return {"kind": "chart", "h": title, "type": "line", "labels": [m["month"] for m in ms],
            "series": [{"name": idx.get("method", "index"), "data": [m["index"] for m in ms]}], "yfmt": None}


def _legal_notes(rows) -> list[dict]:
    out = []
    for r in rows:
        f = legal_flag(r.get("legal"))
        if f:
            out.append(_note(f"{r.get('name') or r.get('subject') or r.get('listing_id') or r.get('id')}: {f}", "bad"))
    return out


# ------------------------------------------------------------------ market

def market(p: dict, as_of: str) -> dict:
    m, ys = p.get("market", {}), p.get("yields", [])
    scope = m.get("scope", "city")
    land = m.get("landscape", {})
    sup = land.get("supply", {})
    disp, dom, cuts = land.get("dispersion", {}), land.get("days_on_market", {}), land.get("price_cuts", {})
    gy = m.get("gross_yield", {})
    secs = [{"kind": "kpis", "h": "Level and liquidity", "items": [
        ["Active listings", str(sup.get("n", "—"))],
        ["Median asking /m²", vnd(disp.get("median_m2"))],
        ["Median days on market", num(dom.get("median_completed"), 0)],
        ["Cut rate (90d)", pct(cuts.get("cut_rate"))],
        ["Asking gross yield", pct(gy.get("yield"))]]}]
    secs += [_note(n) for n in land.get("notes", [])]
    rows = [r for r in m.get("ppm2", []) if True]
    if rows:
        secs.append({"kind": "table", "h": "Asking price per m² by month", "cols": ["Type", "Month", "n", "Median",
                                                                                     "Q1", "Q3"],
                     "rows": [[r.get("ptype") or "all", r["month"], str(r["n"]),
                               vnd(r.get("median")) if not r.get("insufficient") else "thin",
                               vnd(r.get("q1")), vnd(r.get("q3"))] for r in rows[-40:]], "text_cols": [0, 1]})
    for key, title in (("repeat_index", "Repeat-listing index (asking)"), ("hedonic_index", "Hedonic index (asking)")):
        ch = _index_chart(m.get(key), title)
        if ch:
            secs.append(ch)
        elif _insuf(m.get(key)):
            secs.append(_note(f"{title}: insufficient — {_insuf(m.get(key))}", "warn"))
    if ys:
        secs.append({"kind": "table", "h": "Asking gross yields", "cols": ["Ward", "Type", "Yield", "n rent", "n sale",
                                                                          "Note"],
                     "rows": [[y.get("ward_code"), y.get("ptype"), pct(y.get("yield")), str(y.get("n_rent", "—")),
                               str(y.get("n_sale", "—")), y.get("reason") or ""] for y in ys], "text_cols": [0, 1, 5]})
    return {"title": f"Market — {scope}", "subtitle": m.get("ptype") or "all types", "meta": _meta(as_of),
            "sections": secs}


# ------------------------------------------------------------------ listing

def listing(p: dict, as_of: str) -> dict:
    v = p.get("value", {})
    s = v.get("subject", {})
    comb = v.get("combined", {})
    secs = [{"kind": "kpis", "h": "Value vs asking", "items": [
        ["Asking", vnd(s.get("ask"))], ["Triangulated value", vnd(comb.get("value"))],
        ["Band", f"{vnd(comb.get('lo'))} – {vnd(comb.get('hi'))}"],
        ["Gap to asking", signed(v.get("gap_to_ask"), pct)], ["Area", f"{num(s.get('area_m2'), 0)} m²"]]}]
    sc = (p.get("score") or {}).get("grade") or {}
    if sc:
        secs.append({"kind": "grade", "grade": sc.get("letter") or "—",
                     "score": round(sc["score"]) if sc.get("score") is not None else "",
                     "text": sc.get("verdict") or ("withheld: missing " + ", ".join(sc.get("missing", [])))})
    f = legal_flag(s.get("legal"))
    if f:
        secs.append(_note(f"Title: {f}", "bad"))
    elif s.get("legal") in (None, "unknown", "co_so"):
        secs.append(_note(f"Title type not established ({s.get('legal') or 'unknown'}): verify at the land office.",
                          "warn"))
    rows = []
    for name, e in (v.get("methods") or {}).items():
        rows.append([name, vnd(e.get("value")), vnd(e.get("lo")), vnd(e.get("hi")), str(e.get("n", "")),
                     e.get("reason", "") if e.get("status") == "insufficient" else ""])
    of = v.get("official_floor") or {}
    rows.append(["official (floor)", vnd(of.get("value")), "", "", "", of.get("reason") or of.get("role", "")])
    secs.append({"kind": "table", "h": "Methods", "cols": ["Method", "Value", "Lo", "Hi", "n", "Note"], "rows": rows,
                 "text_cols": [0, 5]})
    comps = p.get("comps") or []
    if comps:
        secs.append({"kind": "table", "h": "Comparables (adjusted)", "cols": ["Listing", "Kind", "Seen", "Area",
                                                                            "Price/m²", "Adj /m²"],
                     "rows": [[str(c.get("listing_id")), c.get("kind"), str(c.get("seen_at"))[:10],
                               num(c.get("area_m2"), 0), vnd(c.get("price_m2")), vnd(c.get("adj_price_m2"))]
                              for c in comps[:30]], "text_cols": [0, 1, 2]})
    hist = [h for h in p.get("history") or [] if h.get("price")]
    if len(hist) >= 2:
        secs.append({"kind": "chart", "h": "Observed prices", "type": "line",
                     "labels": [h["seen_at"][:10] for h in hist],
                     "series": [{"name": "asking", "data": [h["price"] for h in hist]}], "yfmt": "b"})
    pts = []
    if s.get("lat") is not None and s.get("lng") is not None:
        pts.append({"lat": s["lat"], "lng": s["lng"], "label": s.get("subject"), "layer": "subject"})
    for pr in p.get("projects") or []:
        if pr.get("lat") is not None:
            pts.append({"lat": pr["lat"], "lng": pr["lng"], "label": pr.get("name_en") or pr.get("name_vi") or pr["id"],
                        "layer": "project"})
    if pts:
        secs.append({"kind": "map", "h": "Location and projects", "points": pts})
    cites = [{"title": e.get("title") or e.get("claim") or e.get("url"), "url": e.get("url")}
             for pr in p.get("projects") or [] for e in pr.get("evidence", [])]
    if s.get("url"):
        cites.insert(0, {"title": "Listing page", "url": s["url"], "date": str(s.get("ask_seen_at"))[:10]})
    if cites:
        secs.append({"kind": "cites", "h": "Sources", "items": cites})
    return {"title": f"Listing {s.get('subject', '')}", "subtitle": s.get("title") or "",
            "meta": _meta(as_of, "Valuation not recorded by the report (run `value` to record)."), "sections": secs}


# ------------------------------------------------------------------ deal

def deal(p: dict, as_of: str) -> dict:
    m = p.get("metrics", {})
    st = m.get("stable", {})
    e = p.get("ev", {})
    secs = [{"kind": "kpis", "h": "Base case", "items": [
        ["Cash in", vnd(m.get("cash_in"))], ["Equity IRR", pct(m.get("irr"))], ["NPV at hurdle", signed(m.get("npv"))],
        ["Stabilised DSCR", num(st.get("dscr"))], ["Monthly cash", signed(st.get("cash"))],
        ["Max loan at DSCR", vnd(m.get("loan_max"))]]},
        {"kind": "kpis", "h": "Expected value", "items": [
            ["E[NPV]", signed(e.get("expected_npv"))], ["P(loss)", pct(e.get("p_loss"))],
            ["P(IRR < hurdle)", pct(e.get("p_irr_below_hurdle"))], ["Scenarios", p.get("scenario_basis", "")]]}]
    if not m.get("passes", True):
        secs.append(_note("Fails: " + ", ".join(m.get("reasons", [])), "bad"))
    for k in p.get("kill", []):
        secs.append(_note("Kill trigger: " + k.get("detail", k.get("rule", "")), "bad"))
    secs.append({"kind": "table", "h": "Scenarios", "cols": ["Scenario", "p", "IRR", "NPV", "DSCR", "Profit"],
                 "rows": [[r["name"], pct(r["p"], 0), pct(r.get("irr")), vnd(r.get("npv")), num(r.get("dscr")),
                           vnd(r.get("profit"))] for r in e.get("scenarios", [])], "text_cols": [0]})
    secs.append({"kind": "table", "h": "Stress", "cols": ["Shock", "IRR", "NPV", "DSCR", "Monthly cash", "Passes"],
                 "rows": [[k, pct(r.get("irr")), vnd(r.get("npv")), num(r.get("dscr")), vnd(r.get("stable_cash")),
                           "yes" if r.get("passes") else "no"] for k, r in (p.get("stress") or {}).items()],
                 "text_cols": [0, 5]})
    ys = p.get("yearly", [])
    if ys:
        secs.append({"kind": "chart", "h": "Yearly cash and equity", "type": "bar", "labels": [str(y["year"]) for y in ys],
                     "series": [{"name": "cash", "data": [y["cash"] for y in ys]},
                                {"name": "equity", "data": [y["equity"] for y in ys]}], "yfmt": "b"})
    return {"title": f"Deal — {p.get('file', '')}", "meta": _meta(as_of, "Scenario weights are judgement priors "
                                                                          "unless a scenarios file was given."),
            "sections": secs}


# ------------------------------------------------------------------ compare

def compare(p: dict, as_of: str) -> dict:
    rows = p.get("rows", [])
    secs = []
    if rows:
        secs.append({"kind": "table", "h": "Side by side", "cols": ["Item", "Price", "Price/m²", "Value gap",
                                                                    "Gross yield", "Cash on cash", "DSCR", "IRR", "NPV",
                                                                    "Legal"],
                     "rows": [[r["name"], vnd(r.get("price")), vnd(r.get("price_m2")), signed(r.get("value_gap"), pct),
                               pct(r.get("yield_gross")), pct(r.get("cash_on_cash")), num(r.get("dscr")),
                               pct(r.get("irr")), signed(r.get("npv")), (r.get("extra") or {}).get("legal") or "—"]
                              for r in rows], "text_cols": [0, 9]})
        secs += _legal_notes([{"name": r["name"], "legal": (r.get("extra") or {}).get("legal")} for r in rows])
        ranks = p.get("ranks", {})
        secs.append({"kind": "table", "h": "Rank per metric (best first)", "cols": ["Metric", "Order"],
                     "rows": [[k, " > ".join(v)] for k, v in ranks.items()], "text_cols": [0, 1]})
    for pr in p.get("problems", []):
        secs.append(_note(f"{pr['item']}: {pr['reason']}", "warn"))
    return {"title": "Comparison", "meta": _meta(as_of), "sections": secs or [_note("Nothing comparable.", "warn")]}


# ------------------------------------------------------------------ portfolio

def portfolio(p: dict, as_of: str) -> dict:
    pf = p.get("portfolio", {})
    tot = pf.get("total", {})
    occ = pf.get("occupancy", {})
    secs = [{"kind": "kpis", "h": "Book", "items": [
        ["Value", vnd(tot.get("value"))], ["Debt", vnd(tot.get("debt"))], ["Equity", vnd(tot.get("equity"))],
        ["NOI ttm", vnd(tot.get("noi_ttm"))], ["Occupancy", pct(occ.get("rate"))]]}]
    units = pf.get("units", [])
    if units:
        secs.append({"kind": "table", "h": "Units", "cols": ["Unit", "Value", "Debt", "Equity", "NOI ttm",
                                                            "Yield on value"],
                     "rows": [[u.get("name") or u.get("id"), vnd(u.get("value")), vnd(u.get("debt")),
                               vnd(u.get("equity")), vnd(u.get("noi_ttm")), pct(u.get("yield_on_value"))]
                              for u in units], "text_cols": [0]})
        secs += _legal_notes(units)
    for g in pf.get("gaps", []):
        secs.append(_note(f"Gap: {g}", "warn"))
    rr = pf.get("rent_roll", [])
    if rr:
        secs.append({"kind": "table", "h": "Rent roll", "cols": ["Unit", "Tenant", "Rent", "Start", "End"],
                     "rows": [[r.get("unit_id"), r.get("tenant") or "", vnd(r.get("rent")), r.get("start") or "",
                               r.get("end") or ""] for r in rr], "text_cols": [0, 1, 3, 4]})
    cl = p.get("close")
    if cl:
        secs.append({"kind": "kpis", "h": f"Close {cl.get('month')}", "items": [
            ["Expected rent", vnd(cl.get("expected_rent"))], ["Received", vnd(cl.get("received_rent"))],
            ["Collection", pct(cl.get("collection_rate"))], ["Net cash", signed(cl.get("net_cash"))]]})
        secs += [_note(str(x.get("text", x)) if isinstance(x, dict) else str(x), "warn") for x in cl.get("alerts", [])]
    rk = p.get("risk")
    if rk:
        secs.append({"kind": "kpis", "h": "Risk", "items": [
            ["LTV", pct(rk.get("ltv"))], ["DSCR", num(rk.get("dscr"))],
            ["Liquidity months", num(rk.get("liquidity_months"), 1)]]})
        for f in rk.get("flags", []):
            secs.append(_note(f"{f.get('code')}: {f.get('value')} vs {f.get('threshold')} ({f.get('severity')})",
                              "bad" if f.get("severity") == "high" else "warn"))
    return {"title": "Portfolio", "meta": _meta(as_of), "sections": secs}


# ------------------------------------------------------------------ plan

def plan(p: dict, as_of: str) -> dict:
    opts = p.get("options", {})
    rows = []
    for name, o in opts.items():
        if not isinstance(o, dict):
            continue
        if "insufficient" in o:
            rows.append([name, "—", "—", "—", "—", "insufficient: " + str(o["insufficient"])])
            continue
        be = o.get("break_even") or {}
        rows.append([name, vnd(o.get("cash_in")), signed(o.get("stable_cash")), pct(o.get("irr")),
                     vnd(be.get("income")) if isinstance(be, dict) and "income" in be else "—",
                     "" if o.get("passes") else "fails base-case test"])
    rec = p.get("recommendation") or {}
    lot = p.get("lot") or {}
    secs = [{"kind": "kpis", "h": "Lot", "items": [["Value", vnd(lot.get("value"))],
                                                  ["Area", f"{num(lot.get('area_m2'), 0)} m²"],
                                                  ["Hurdle", pct(p.get("hurdle"))],
                                                  ["Value source", p.get("value_source", "")]]}]
    if rec:
        secs.append(_note(f"Recommendation: {rec.get('option')} — " + "; ".join(str(x) for x in rec.get("reasons", []))))
    else:
        secs.append(_note("No eligible option: every option is excluded (see below).", "warn"))
    secs.append({"kind": "table", "h": "Options", "cols": ["Option", "Money in", "Net cash / month", "IRR",
                                                          "Break-even income", "Note"], "rows": rows,
                 "text_cols": [0, 5]})
    ex = p.get("excluded") or {}
    items = ex.items() if isinstance(ex, dict) else [(e.get("option") or e.get("name"), e.get("reason")) for e in ex]
    for name, why in items:
        secs.append(_note(f"Excluded {name}: {why}", "warn"))
    return {"title": "Plan for the lot", "subtitle": p.get("file", ""), "meta": _meta(as_of), "sections": secs}


# ------------------------------------------------------------------ screen

def screen(p: dict, as_of: str) -> dict:
    secs = []
    if "pricing" in p.get("results", {}):
        secs += _pricing_sections(p["results"]["pricing"])
    hits = p.get("hits", [])
    if hits:
        secs.append({"kind": "table", "h": "Hits", "cols": ["Listing", "Type", "Ward", "Price", "Rules", "Why"],
                     "rows": [[str(h["listing_id"]), h.get("ptype"), h.get("ward_code") or "", vnd(h.get("price")),
                               ", ".join(h.get("rules", [])), " | ".join(h.get("why", []))] for h in hits],
                     "text_cols": [0, 1, 2, 4, 5]})
        secs += _legal_notes(hits)
    for rule, why in (p.get("insufficient") or {}).items():
        secs.append(_note(f"{rule}: insufficient — {why}", "warn"))
    if p.get("caveat"):
        secs.append(_note(p["caveat"]))
    return {"title": f"Screen — {p.get('rule')}", "subtitle": f"universe {p.get('universe', '—')} listings",
            "meta": _meta(as_of), "sections": secs or [_note("No hits.", "warn")]}


_UNIT_SHORT = {"VND/m² land": "/m² land", "VND/m² floor area": "/m² floor", "VND/m²": "/m²", "VND per frontage metre": "/m frontage",
               "VND per room": "/room", "VND/m² buildable floor area": "/m² buildable"}


def _metric_cell(km: dict) -> str:
    if not km or km.get("value") is None:
        return "—"
    u = km.get("unit") or ""
    return vnd(km["value"]) + _UNIT_SHORT.get(u, (" " + u) if u and not u.startswith("VND") else "")


def _pricing_sections(r: dict) -> list[dict]:
    """Pricing screen: a ranked table per property type (rank within type, on the confidence-shrunk score), the key
    metric against its peers, the strongest reason, flags, and a map of the ranked listings."""
    if not isinstance(r, dict):
        return []
    secs = [{"kind": "kpis", "h": "Universe", "items": [
        ["Active sale listings", str(r.get("n_active", "—"))], ["Evaluated", str(r.get("n_evaluated", "—"))],
        ["Scored", str(r.get("n_scored", "—"))]] + [[f"Scored: {t}", str(n)] for t, n in sorted((r.get("n_scored_by_type") or {}).items())]},
        _note("Ranks are within each property type: their metrics and peers differ, so scores are not compared across types. "
              "Rank score = 50 + (score − 50) × confidence, so a high score built on little evidence is pulled toward neutral. "
              f"Hedonic model: {r.get('hedonic')}.")]
    pts = []
    for t, rows in sorted((r.get("by_type") or {}).items(), key=lambda kv: -len(kv[1])):
        if not rows:
            continue
        km0 = rows[0].get("key_metric") or {}
        secs.append({"kind": "table", "h": f"{t} — top {len(rows)} of {rows[0].get('type_n', len(rows))} scored",
                     "p": f"Key metric: {km0.get('name')} vs peers (scope widens ward → district → city when thin).",
                     "cols": ["#", "Listing", "Ward", "Price", "Area", "Key metric", "Peer median", "Pctile", "z",
                              "Score", "Conf.", "Rank score", "Strongest reason", "Flags"],
                     "rows": [[str(x.get("type_rank", "")), str(x.get("id")), x.get("ward") or "", vnd(x.get("price")),
                               num(x.get("area_m2"), 0), _metric_cell(x.get("key_metric") or {}),
                               _metric_cell({**(x.get("key_metric") or {}), "value": (x.get("key_metric") or {}).get("peer_median")}),
                               num((x.get("key_metric") or {}).get("percentile"), 0), num((x.get("key_metric") or {}).get("z"), 1),
                               num(x.get("score"), 0), pct(x.get("confidence"), 0),
                               {"v": num(x.get("rank_score"), 0), "cls": "pos" if (x.get("rank_score") or 0) >= 65 else ""},
                               ((x.get("why") or {}).get("strongest") or [{}])[0].get("text", ""),
                               {"v": "; ".join(x.get("flags") or []), "cls": "warnc" if x.get("flags") else ""}]
                              for x in rows],
                     "text_cols": [1, 2, 12, 13]})
        pts += [{"lat": x["lat"], "lng": x["lng"], "layer": t,
                 "label": f"#{x.get('type_rank')} {t} · {vnd(x.get('price'))} · score {num(x.get('score'), 0)} · listing {x.get('id')}"}
                for x in rows if x.get("lat") is not None and x.get("lng") is not None]
    if pts:
        secs.append({"kind": "map", "h": "Where the ranked listings are", "points": pts,
                     "cap": "Coordinates as the site gives them; unpinned ads sit at approximate points."})
    return secs


# ------------------------------------------------------------------ strategy

def strategy(p: dict, as_of: str) -> dict:
    ranked = p.get("ranked", [])
    secs = []
    if ranked:
        b = ranked[0]
        secs.append({"kind": "kpis", "h": f"Best: {b['strategy']}", "items": [
            ["Score", num(b.get("score"), 3)], ["IRR", pct((b.get("metrics") or {}).get("irr"))],
            ["E[NPV]", signed((b.get("ev") or {}).get("expected_npv"))], ["P(loss)", pct((b.get("ev") or {}).get("p_loss"))],
            ["Peak cash", vnd(b.get("peak_cash"))]]})
    secs.append({"kind": "table", "h": "Ranked strategies", "cols": ["Strategy", "Score", "IRR", "E[NPV]", "Bear NPV",
                                                                     "P(loss)", "Peak cash", "Kill"],
                 "rows": [[r["strategy"], num(r.get("score"), 3), pct((r.get("metrics") or {}).get("irr")),
                           vnd((r.get("ev") or {}).get("expected_npv")),
                           vnd(((r.get("ev") or {}).get("bear") or {}).get("npv")), pct((r.get("ev") or {}).get("p_loss")),
                           vnd(r.get("peak_cash")), ", ".join(k.get("rule", "") for k in r.get("kill", []))]
                          for r in ranked], "text_cols": [0, 7]})
    for e in p.get("excluded", []):
        secs.append(_note(f"Excluded {e['strategy']}: {e['reason']}", "warn"))
    if p.get("formula"):
        secs.append(_note("Score: " + p["formula"]))
    secs.append(_note(f"Profile: {p.get('profile_source', '')}"))
    return {"title": "Strategies", "subtitle": p.get("file", ""), "meta": _meta(as_of), "sections": secs}


# ------------------------------------------------------------------ asset (one owned unit)

_BAD_STATUS = {"encroached", "disputed", "frozen", "seized", "blocked"}


def asset(p: dict, as_of: str) -> dict:
    """One owned unit, everything in one page: status and next actions, value and position, value methods and history,
    plan options and what-ifs, projection and sell timing, money, leases, timeline, legal, notes, images, map, gaps."""
    u, pos = p["unit"], p["position"]
    secs: list[dict] = []
    st = (u.get("status") or "held").lower()
    todo = [a for a in p.get("actions", []) if (a.get("status") or "todo") not in ("done", "dropped")]
    if st in _BAD_STATUS:
        secs.append(_note(f"Status: {st}. " + (f"Open action: {todo[0].get('step')} — {todo[0].get('why', '')}" if todo else
                                               "Resolve the status before any use or sale."), "bad"))
    floors = None
    if u.get("alley_m") is not None:
        floors = "street frontage" if u["alley_m"] == 0 else f"{u['alley_m']:g} m kiệt"
    secs.append({"kind": "kpis", "h": "Position", "items": [
        ["Value (whole)", vnd(p.get("value"))], ["Range", f"{vnd(p.get('lo'))} – {vnd(p.get('hi'))}"],
        [f"Your share ({pct(pos.get('share'), 1)})", vnd(pos.get("own_value"))], [f"You paid ({pos.get('paid_basis')})", vnd(pos.get("paid"))],
        ["Gain", signed(pos.get("gain"))], ["Return a year", pct(pos.get("cagr"))],
        ["Equity after debt", vnd(pos.get("equity"))], ["Price per m²", vnd(pos.get("price_m2"))],
        ["Area", f"{num(u.get('area_m2'), 0)} m²"], ["Access", floors or "unknown"], ["Title", u.get("legal") or "unknown"]]})
    if todo or p.get("actions"):
        secs.append({"kind": "table", "h": "Actions", "cols": ["Step", "Status", "Why"],
                     "rows": [[a.get("step", ""), {"v": a.get("status", "todo"), "cls": "warnc" if a.get("status", "todo") != "done" else "pos"},
                               a.get("why", "")] for a in p.get("actions", [])], "text_cols": [0, 1, 2]})
    if p.get("methods"):
        secs.append({"kind": "table", "h": "How the value is built", "cols": ["Method", "Value", "Low", "High", "n", "Note"],
                     "rows": [[m["method"], vnd(m.get("value")), vnd(m.get("lo")), vnd(m.get("hi")), str(m.get("n") or ""),
                               m.get("reason", "") if m.get("status") != "ok" else ""] for m in p["methods"]],
                     "text_cols": [0, 5], "cap": "Comparables are asking prices with the cited asking→sale haircut applied. "
                                                  "An 'insufficient' method says what it lacks; it is never filled in."})
    vh = [r for r in p.get("value_history", []) if r.get("method") in ("combined", "triangulated") and r.get("value")]
    if len(vh) >= 2:
        secs.append({"kind": "chart", "h": "Value over time (recorded valuations)", "labels": [r["as_of"] for r in vh], "yfmt": "b",
                     "series": [{"name": "value", "data": [r["value"] for r in vh]}, {"name": "low", "data": [r["lo"] for r in vh], "dash": True},
                                {"name": "high", "data": [r["hi"] for r in vh], "dash": True}]})
    pl = p.get("plan") or {}
    if pl.get("ranking"):
        rows = []
        for name in pl["ranking"]:
            o = (pl.get("options") or {}).get(name) or {}
            a = o.get("analysis") or o
            be = o.get("break_even_rent") or {}
            rows.append([name, pct(a.get("irr")), signed(a.get("npv")), vnd(a.get("peak_cash_out")),
                         vnd(be.get("per_unit") or be.get("rent")) if isinstance(be, dict) else "—"])
        rec = pl.get("recommendation") or {}
        secs.append({"kind": "table", "h": "What to do with it", "cols": ["Option", "Equity IRR", "NPV at hurdle", "Peak cash", "Rent needed (hurdle)"],
                     "rows": rows, "text_cols": [0]})
        if rec.get("reasons"):
            secs.append(_note("; ".join(rec["reasons"]), "" if rec.get("clears_hurdle") else "warn"))
        if pl.get("excluded"):
            secs.append(_note("Not priced (inputs missing): " + "; ".join(f"{k}: {v}" for k, v in pl["excluded"].items()), "warn"))
    if p.get("sensitivities"):
        secs.append({"kind": "table", "h": "What-ifs", "cols": ["Change", "Best option", "Its IRR", "Build studios IRR", "Sell & deposit IRR"],
                     "rows": [[s["name"], s.get("best") or "—", pct(s.get("irr")), pct(s.get("build_studios")), pct(s.get("sell_deposit"))]
                              for s in p["sensitivities"]], "text_cols": [0, 1]})
    pr = p.get("projection") or {}
    mc, pth = pr.get("monte_carlo") or {}, pr.get("paths") or {}
    if mc.get("years"):
        v0 = p.get("value") or 0
        series = [{"name": "p50 (Monte Carlo)", "data": mc["p50"]}, {"name": "p10", "data": mc["p10"], "dash": True},
                  {"name": "p90", "data": mc["p90"], "dash": True}]
        if pth.get("base") and v0:
            series.append({"name": "base path (catalysts at their chance)", "data": [v0 * m for m in pth["base"]][:len(mc["years"])]})
        secs.append({"kind": "chart", "h": "Where the price could go", "labels": [str(y) for y in mc["years"]], "series": series, "yfmt": "b",
                     "cap": f"Drift and volatility: {(pr.get('market') or {}).get('basis', 'own index')}; catalysts within reach: "
                            + (", ".join((pth.get('contrib') or {}).keys()) or "none")})
    hv = (pr.get("hold_vs_sell") or {}) if isinstance(pr.get("hold_vs_sell"), dict) else {}
    if hv.get("rows"):
        secs.append({"kind": "table", "h": "Sell now, or hold?", "cols": ["Year", "Price (base)", "Take-home if sold", "Sell now + deposit", "Hold vs sell now"],
                     "rows": [[str(r["year"]), vnd(r["price"]), vnd(r["take_home"]), vnd(r["deposit"]), signed(r["edge"])] for r in hv["rows"]],
                     "text_cols": [], "cap": "Take-home is your share after the 2% transfer tax and selling costs."})
    if p.get("funding"):
        secs.append({"kind": "table", "h": "How it was paid for", "cols": ["Source", "Amount", "Yours"],
                     "rows": [[f.get("source", ""), vnd(f.get("amount")), "yes" if f.get("yours") else "no"] for f in p["funding"]], "text_cols": [0]})
    if p.get("txns"):
        secs.append({"kind": "table", "h": f"Money in and out ({p.get('txns_source')})", "cols": ["Date", "Category", "Amount", "Note"],
                     "rows": [[str(t.get("at", "")), t.get("category", ""), signed(t.get("amount")), t.get("memo") or t.get("note") or ""]
                              for t in p["txns"]], "text_cols": [0, 1, 3]})
    if p.get("leases"):
        secs.append({"kind": "table", "h": "Leases", "cols": ["Tenant", "Start", "End", "Rent", "Deposit", "Status"],
                     "rows": [[l.get("tenant") or "", l.get("start") or "", l.get("end") or "", vnd(l.get("rent")), vnd(l.get("deposit")),
                               l.get("status") or ""] for l in p["leases"]], "text_cols": [0, 1, 2, 5]})
    if p.get("timeline"):
        secs.append({"kind": "table", "h": "Timeline", "cols": ["When", "What", "Source"],
                     "rows": [[str(e.get("date", "")), e.get("event", ""), e.get("source", "")] for e in p["timeline"]], "text_cols": [0, 1, 2]})
    lg = p.get("legal") or {}
    if lg.get("items"):
        secs.append({"kind": "table", "h": f"Due diligence — {lg.get('overall', '')}", "cols": ["Item", "Status", "Note"],
                     "rows": [[i.get("label_en") or i.get("item") or i.get("id", ""), {"v": i.get("status", "open"), "cls": "neg" if i.get("status") == "issue" else ("pos" if i.get("status") == "ok" else "warnc")},
                               i.get("note") or ""] for i in lg["items"]], "text_cols": [0, 1, 2]})
    if p.get("journal"):
        secs.append({"kind": "table", "h": "Notes", "cols": ["When", "Kind", "Note"],
                     "rows": [[str(j["at"])[:10], j["kind"], j["body"]] for j in p["journal"]], "text_cols": [0, 1, 2]})
    imgs = [{"src": v, "caption": k} for k, v in (p.get("images") or {}).items() if isinstance(v, str)]
    if imgs:
        secs.append({"kind": "images", "h": "Images", "items": imgs})
    pts = []
    if u.get("lat") is not None and u.get("lng") is not None:
        pts.append({"lat": u["lat"], "lng": u["lng"], "label": u.get("name") or u["id"], "layer": "this unit", "r": 9})
    pts += [{"lat": x["lat"], "lng": x["lng"], "label": f"{x.get('name_en') or x.get('name_vi') or x['id']} ({x.get('status') or ''})", "layer": "projects"}
            for x in p.get("projects", []) if x.get("lat") is not None and x.get("lng") is not None]
    if pts:
        secs.append({"kind": "map", "h": "Location and nearby projects", "points": pts})
    if p.get("gaps"):
        secs.append(_note("Known gaps: " + "; ".join(str(g) for g in p["gaps"]), "warn"))
    if p.get("documents"):
        secs.append({"kind": "table", "h": "Documents (local, private)", "cols": ["Document", "Where"],
                     "rows": [[d.get("name", ""), d.get("path", "")] for d in p["documents"]], "text_cols": [0, 1]})
    return {"title": u.get("name") or u["id"], "subtitle": f"Owned unit {u['id']} · {u.get('address') or u.get('ward_code') or ''}",
            "meta": _meta(as_of, "PRIVATE — contains owner records; do not publish."), "sections": secs}
