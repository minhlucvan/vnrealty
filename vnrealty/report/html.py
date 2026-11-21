"""Render a report (a title plus a list of sections) to a self-contained HTML dashboard and a Markdown dossier.

A report is plain data, built by the CLI from library outputs:

    {"title": str, "subtitle": str?, "meta": str?, "sections": [section, ...]}

Section kinds: ``kpis`` (items: [[label, cell]]), ``table`` (cols, rows, text_cols?), ``chart`` (type, labels,
series: [{name, data, dash?, fill?}], yfmt: 'b'|'m'|'pct'|None), ``note`` (text, tone: ''|'warn'|'bad'), ``grade``
(grade, score, text), ``cites`` (items: [{title, url, date}]), ``map`` (points: [{lat, lng, label, layer, r?}] on OpenStreetMap), ``images`` (items: [{src, caption}], paths relative
to the report). Every section may have ``h``, ``p`` and ``cap``.
Cells are strings or {"v": text, "cls": "pos"|"neg"|"warnc"}. Formatting is done before this point (report/fmt.py).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from ..store.db import REPO

__all__ = ["render_html", "render_md", "write_report", "TEMPLATE"]

TEMPLATE = REPO / "web" / "templates" / "dashboard.html"
_MARK = "/*__DATA__*/"


def render_html(report: dict, template: Path = TEMPLATE) -> str:
    """Embed the report JSON in the dashboard template. '</' is escaped so page text can never close the script."""
    t = template.read_text(encoding="utf-8")
    i = t.index(_MARK)
    j = t.index(";", i)   # the default object after the marker ends at the first ';'
    payload = json.dumps(report, ensure_ascii=False, default=str).replace("</", "<\\/")
    return t[:i] + payload + t[j:]


def _cell(c) -> str:
    if isinstance(c, dict):
        return str(c.get("v", re.sub(r"<[^>]+>", "", str(c.get("html", "")))))
    return str(c).replace("|", "\\|")


def render_md(report: dict) -> str:
    out = [f"# {report['title']}", ""]
    if report.get("subtitle"):
        out += [report["subtitle"], ""]
    if report.get("meta"):
        out += [f"_{report['meta']}_", ""]
    for s in report["sections"]:
        if s.get("h"):
            out += [f"## {s['h']}", ""]
        if s.get("p"):
            out += [s["p"], ""]
        k = s.get("kind")
        if k == "kpis":
            out += ["| " + " | ".join(str(a) for a, _ in s["items"]) + " |", "|" + "---|" * len(s["items"]),
                    "| " + " | ".join(_cell(b) for _, b in s["items"]) + " |", ""]
        elif k == "table":
            out += ["| " + " | ".join(s["cols"]) + " |", "|" + "---|" * len(s["cols"])]
            out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in s["rows"]] + [""]
        elif k == "note":
            out += [("> ⚠ " if s.get("tone") else "> ") + s["text"], ""]
        elif k == "grade":
            out += [f"**Grade {s['grade']}** ({s.get('score', '')}) — {s['text']}", ""]
        elif k == "chart":
            out += [f"_Chart: {', '.join(d['name'] for d in s['series'])} over {len(s['labels'])} points (see the HTML report)._", ""]
        elif k == "images":
            out += [f"![{m.get('caption', '')}]({m['src']})" for m in s.get("items", [])] + [""]
        elif k == "map":
            out += [f"_Map: {len(s.get('points', []))} points (see the HTML report)._", ""]
        elif k == "cites":
            out += [f"- [{c.get('title') or c.get('url')}]({c.get('url', '')})" + (f" · {c['date']}" if c.get("date") else "") for c in s["items"]] + [""]
        if s.get("cap"):
            out += [f"_{s['cap']}_", ""]
    out += ["---", "_vnrealty — decision support for the owner, not financial or legal advice. Asking prices are not sale prices._"]
    return "\n".join(out) + "\n"


def write_report(report: dict, kind: str, slug: str, out_dir: Path | None = None) -> dict:
    """Write <kind>-<slug>-<date>.html and .md under data/reports/ (private). Returns both paths."""
    d = out_dir or REPO / "data" / "reports"
    d.mkdir(parents=True, exist_ok=True)
    stem = f"{kind}-{re.sub(r'[^a-zA-Z0-9_-]+', '-', slug).strip('-') or 'report'}-{_dt.date.today().isoformat()}"
    h, m = d / f"{stem}.html", d / f"{stem}.md"
    h.write_text(render_html(report), encoding="utf-8")
    m.write_text(render_md(report), encoding="utf-8")
    return {"html": str(h), "md": str(m)}
