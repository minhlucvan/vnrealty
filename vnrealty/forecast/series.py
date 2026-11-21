"""Monthly area price series: store, read point in time, chain-link sources, index, regularise.

Storage is the ``price_series`` table (one row per source × scope × ptype × kind × month × vintage ``seen_at``). A later
vintage of the same month (a chart re-captured after the site revised it) is a new row, never an overwrite.

Reading (:func:`get_series`) is point in time: for each month the value from the latest ``seen_at <= as_of`` is used,
and months after ``as_of`` are never returned. Sources are kept apart, one :class:`Series` each.

Chain-linking (:func:`splice`): two sources are linked only where they overlap. The ratio is the geometric mean of
``base / other`` over the overlapping months (``min_overlap`` months at least, default 3); the overlap length and the
dispersion (standard deviation of the log ratios) are reported. Overlapping months keep the base's values. A source
with no (or too short) overlap stays separate — a level is never guessed across a gap between sources.

Regularising (:func:`regularize`): gaps of up to ``max_gap`` (default 3) missing months are filled by log-linear
interpolation and listed in ``filled``; a longer gap is not interpolated — it is marked in ``gaps`` and the months
stay missing. :func:`last_segment` returns the most recent run without unfilled gaps, which is what the models fit.

Units: values in the series unit (``vnd_m2`` = VND per m², ``vnd`` = VND, ``index`` = points); months ``YYYY-MM``;
``seen_at`` ISO-8601.
"""
from __future__ import annotations

import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

from vnrealty.types import Insufficient

__all__ = ["Series", "add_points", "get_series", "splice", "from_capture", "ingest_capture", "to_index", "regularize",
           "last_segment", "norm_month", "month_add", "month_diff", "parse_unit", "subject_for"]

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass
class Series:
    """One source's monthly series. ``points`` are ``(YYYY-MM, value)`` sorted by month, value in ``unit``."""
    source: str
    scope_kind: str
    scope: str
    ptype: str | None
    kind: str
    unit: str
    points: list[tuple[str, float]]
    urls: list[str] = field(default_factory=list)
    vintages: dict[str, str] = field(default_factory=dict)   # month -> seen_at of the value used


def month_add(month: str, k: int) -> str:
    """``YYYY-MM`` shifted by ``k`` months (k may be negative)."""
    y, m = divmod(int(month[:4]) * 12 + int(month[5:7]) - 1 + k, 12)
    return f"{y:04d}-{m + 1:02d}"


def month_diff(a: str, b: str) -> int:
    """Months from ``a`` to ``b`` (b − a)."""
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower()).replace("đ", "d")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip()


def norm_month(x) -> str | None:
    """Normalise a date-ish value to ``YYYY-MM``; None when it cannot be read.

    Accepts ``YYYY-MM``, ``YYYY-MM-DD…``, ``MM/YYYY``, ``T3/2025``, ``Tháng 3/2025``, ``Q1/2025`` / ``Quý 1 2025``
    (quarters map to their middle month), and epoch numbers (milliseconds when > 1e11, else seconds).
    """
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        if not math.isfinite(x) or x <= 1e9:
            return None
        from datetime import datetime, timezone
        d = datetime.fromtimestamp(x / 1000 if x > 1e11 else x, tz=timezone.utc)
        return f"{d.year:04d}-{d.month:02d}"
    s = _fold(x)
    m = re.match(r"^(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    m = re.search(r"(?:q|quy)\s*([1-4])\s*[/\-\s]\s*(\d{4})", s)
    if m:
        return f"{int(m.group(2)):04d}-{3 * int(m.group(1)) - 1:02d}"
    m = re.search(r"(?:^|[^\d])(\d{1,2})\s*[/\-.]\s*(\d{4})(?:$|[^\d])", s) or \
        re.search(r"(?:t|thang|th)\s*(\d{1,2})\s*[/\-\s,]\s*(\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)     # DD/MM/YYYY
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(3)):04d}-{int(m.group(2)):02d}"
    return None


def _num(v) -> float | None:
    """A chart value as float: numbers pass; text like '72,5' or '1.250' is read with Vietnamese separators."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = re.sub(r"[^\d,.\-]", "", str(v))
    if not s:
        return None
    if "," in s and "." in s:          # 1.250,5 -> 1250.5
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) != 3 else s.replace(",", "")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[-1]) == 3 and len(s.split(".")[0]) <= 3
                              and float(s.replace(".", "")) >= 1000):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_unit(text: str | None) -> tuple[str, float] | None:
    """Map a chart's unit label to ``(unit, multiplier)``: 'triệu/m²' → ('vnd_m2', 1e6), 'tỷ' → ('vnd', 1e9),
    'đ/m2' → ('vnd_m2', 1), '%' / 'điểm' / 'index' → ('index', 1). None when the label is not recognised."""
    if not text:
        return None
    s = _fold(text).replace("²", "2").replace(" ", "")
    per_m2 = "/m2" in s or "m2" in s
    if "trieu" in s or re.search(r"(?:^|[^a-z])tr(?:/|$)", s):
        return ("vnd_m2" if per_m2 else "vnd", 1e6)
    if "ty" in s:
        return ("vnd_m2" if per_m2 else "vnd", 1e9)
    if "nghin" in s or "ngan" in s:
        return ("vnd_m2" if per_m2 else "vnd", 1e3)
    if re.search(r"(vnd|dong|^d/|^d$|d/m2)", s):
        return ("vnd_m2" if per_m2 else "vnd", 1.0)
    if "index" in s or "diem" in s or s == "%":
        return ("index", 1.0)
    return None


def subject_for(source: str, scope_kind: str, scope: str, ptype: str | None) -> str:
    """Forecast subject string for a series: ``series:<source>:<scope_kind>/<scope>:<ptype>`` (ptype may be empty)."""
    return f"series:{source}:{scope_kind}/{scope}:{ptype or ''}"


def add_points(con: sqlite3.Connection, source: str, scope_kind: str, scope: str, ptype: str | None,
               points: list[tuple[str, float]], unit: str, url: str | None, seen_at: str, kind: str = "asking",
               notes: str | None = None) -> int:
    """Insert ``points`` (``(YYYY-MM, value in unit)``) as one vintage seen at ``seen_at``; returns rows inserted.

    Months are normalised with :func:`norm_month`; a point whose month or value cannot be read, or whose value is not
    positive, raises ``ValueError`` (a bad capture should fail loudly, not insert half a series). Re-inserting the same
    vintage is a no-op.
    """
    rows = []
    for m, v in points:
        mm, vv = norm_month(m), _num(v)
        if mm is None or vv is None or vv <= 0:
            raise ValueError(f"unreadable point {m!r}: {v!r}")
        rows.append((source, scope_kind, scope, ptype, kind, mm, vv, unit, url, seen_at, notes))
    n = 0
    for r in rows:      # explicit check: SQLite's UNIQUE treats NULL ptype values as distinct
        if con.execute("SELECT 1 FROM price_series WHERE source = ? AND scope_kind = ? AND scope = ? AND ptype IS ? "
                       "AND kind = ? AND month = ? AND seen_at = ?", (r[0], r[1], r[2], r[3], r[4], r[5], r[9])).fetchone():
            continue
        con.execute("INSERT INTO price_series(source, scope_kind, scope, ptype, kind, month, value, unit, url, seen_at, "
                    "notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)", r)
        n += 1
    con.commit()
    return n


def _end_of(as_of: str) -> str:
    return as_of + "T23:59:59.999" if len(as_of) == 10 else (as_of + "-31T23:59:59.999" if len(as_of) == 7 else as_of)


def get_series(con: sqlite3.Connection, scope_kind: str, scope: str, ptype: str | None, source: str | None = None,
               as_of: str | None = None, kind: str = "asking") -> dict[str, Series]:
    """Point-in-time monthly series per source (``{source: Series}``; key ``source|unit`` if a source mixes units).

    Only rows with ``seen_at <= as_of`` and ``month <= as_of``'s month are used; for each month the latest such
    vintage wins. ``as_of=None`` reads everything.
    """
    q = ("SELECT source, unit, month, value, url, seen_at FROM price_series WHERE scope_kind = ? AND scope = ? "
         "AND ptype IS ? AND kind = ?")
    args: list = [scope_kind, scope, ptype, kind]
    if source is not None:
        q += " AND source = ?"
        args.append(source)
    if as_of is not None:
        q += " AND seen_at <= ? AND month <= ?"
        args += [_end_of(as_of), as_of[:7]]
    q += " ORDER BY source, month, seen_at"
    best: dict[tuple[str, str], dict[str, tuple]] = {}
    for r in con.execute(q, args).fetchall():
        best.setdefault((r[0], r[1]), {})[r[2]] = (r[3], r[4], r[5])      # later seen_at overwrites (ordered)
    units_per_source: dict[str, int] = {}
    for s, _u in best:
        units_per_source[s] = units_per_source.get(s, 0) + 1
    out = {}
    for (s, u), months in best.items():
        key = s if units_per_source[s] == 1 else f"{s}|{u}"
        ms = sorted(months)
        out[key] = Series(s, scope_kind, scope, ptype, kind, u, [(m, float(months[m][0])) for m in ms],
                          sorted({months[m][1] for m in ms if months[m][1]}), {m: months[m][2] for m in ms})
    return out


def splice(series_list: list[Series], min_overlap: int = 3) -> dict:
    """Chain-link sources by their overlap ratio.

    Base = the series ending latest (ties: the longest). Repeatedly, each remaining series overlapping the combined
    series in ≥ ``min_overlap`` months is scaled by ratio = exp(mean(log(base/other))) over the overlap and its
    non-overlapping months are added. Returns ``{base, unit, points, links: [{source, ratio, overlap_months,
    log_ratio_sd}], separate: [{source, overlap_months, reason}]}``; ``points`` are in the base's unit.
    """
    if not series_list:
        return {"base": None, "unit": None, "points": [], "links": [], "separate": []}
    order = sorted(series_list, key=lambda s: (s.points[-1][0] if s.points else "", len(s.points)), reverse=True)
    base = order[0]
    combined = {m: v for m, v in base.points}
    links, rest = [], order[1:]
    progress = True
    while rest and progress:
        progress = False
        for s in list(rest):
            ov = [m for m, _ in s.points if m in combined]
            if len(ov) < min_overlap:
                continue
            sv = dict(s.points)
            lr = [math.log(combined[m] / sv[m]) for m in ov]
            mu = sum(lr) / len(lr)
            sd = math.sqrt(sum((x - mu) ** 2 for x in lr) / (len(lr) - 1)) if len(lr) > 1 else 0.0
            for m, v in s.points:
                combined.setdefault(m, v * math.exp(mu))
            links.append({"source": s.source, "unit": s.unit, "ratio": math.exp(mu), "overlap_months": len(ov),
                          "log_ratio_sd": sd})
            rest.remove(s)
            progress = True
    separate = [{"source": s.source, "overlap_months": sum(1 for m, _ in s.points if m in combined),
                 "reason": f"overlap below {min_overlap} months: level not linked"} for s in rest]
    return {"base": base.source, "unit": base.unit, "points": sorted(combined.items()), "links": links,
            "separate": separate}


def from_capture(obj: dict) -> list[dict]:
    """Rows from a ``browser/pricehistory.js`` capture: one dict per item with ``source`` ('<site>-chart'),
    ``scope_text``, ``ptype_text``, ``unit_text``, ``unit`` and ``multiplier`` (from :func:`parse_unit`; None when the
    label is unknown), ``points`` (normalised months, float values in the *raw* chart unit), ``skipped`` (unreadable
    points), ``url``, ``seen_at``, ``kind``. Raises ``ValueError`` for a capture without ``seen_at`` or ``items``."""
    if not isinstance(obj, dict) or "seen_at" not in obj or "items" not in obj:
        raise ValueError("not a pricehistory capture (needs seen_at and items)")
    out = []
    for it in obj["items"]:
        pts, bad = {}, []
        for p in it.get("points") or []:
            m, v = (norm_month(p[0]), _num(p[1])) if isinstance(p, (list, tuple)) and len(p) >= 2 else (None, None)
            if m is None or v is None or v <= 0:
                bad.append(p)
            else:
                pts[m] = v
        pu = parse_unit(it.get("unit_text"))
        out.append({"source": f"{obj.get('site') or 'unknown'}-chart", "scope_text": it.get("scope_text"),
                    "ptype_text": it.get("ptype_text"), "unit_text": it.get("unit_text"),
                    "unit": pu[0] if pu else None, "multiplier": pu[1] if pu else None,
                    "points": sorted(pts.items()), "skipped": bad, "url": obj.get("url"), "seen_at": obj["seen_at"],
                    "kind": it.get("kind") or "asking"})
    return out


def ingest_capture(con: sqlite3.Connection, obj: dict, scope_kind: str, scope: str, ptype: str | None,
                   item: int = 0, unit: str | None = None, multiplier: float | None = None) -> int | Insufficient:
    """Store item ``item`` of a capture under (scope_kind, scope, ptype). The scope mapping is the caller's (it needs
    geo knowledge the capture does not have). ``Insufficient`` when the unit label is not recognised and no
    ``unit``/``multiplier`` is given — a value with an unknown unit is not stored. Returns rows inserted."""
    rows = from_capture(obj)
    if item >= len(rows):
        return Insufficient("ingest_capture", f"capture has {len(rows)} items, asked for #{item}")
    r = rows[item]
    u, k = unit or r["unit"], multiplier if multiplier is not None else r["multiplier"]
    if u is None or k is None:
        return Insufficient("ingest_capture", f"unrecognised unit label {r['unit_text']!r}: pass unit and multiplier")
    if not r["points"]:
        return Insufficient("ingest_capture", "no readable points", {"skipped": r["skipped"][:5]})
    return add_points(con, r["source"], scope_kind, scope, ptype, [(m, v * k) for m, v in r["points"]], u, r["url"],
                      r["seen_at"], r["kind"], notes=f"scope_text={r['scope_text']!r}; unit_text={r['unit_text']!r}")


def to_index(points: list[tuple[str, float]], base_month: str, base: float = 100.0) -> list[tuple[str, float]] | Insufficient:
    """Rebase to ``base`` (default 100) at ``base_month``; ``Insufficient`` when that month has no value."""
    d = dict(points)
    if not d.get(base_month):
        return Insufficient("to_index", f"no value at base month {base_month}")
    return [(m, base * v / d[base_month]) for m, v in sorted(points)]


def regularize(points: list[tuple[str, float]], max_gap: int = 3) -> dict:
    """Monthly grid from first to last month: ``{points: [(month, value|None)], filled: [months], gaps: [(first
    missing, last missing)]}``. Runs of ≤ ``max_gap`` missing months are log-linearly interpolated (listed in
    ``filled``); longer runs stay None and are listed in ``gaps``."""
    pts = sorted((m, float(v)) for m, v in points if v is not None and v > 0)
    if not pts:
        return {"points": [], "filled": [], "gaps": []}
    out, filled, gaps = [pts[0]], [], []
    for (m0, v0), (m1, v1) in zip(pts, pts[1:]):
        k = month_diff(m0, m1)
        if k > 1:
            if k - 1 <= max_gap:
                for j in range(1, k):
                    mm = month_add(m0, j)
                    out.append((mm, math.exp(math.log(v0) + (math.log(v1) - math.log(v0)) * j / k)))
                    filled.append(mm)
            else:
                out += [(month_add(m0, j), None) for j in range(1, k)]
                gaps.append((month_add(m0, 1), month_add(m1, -1)))
        out.append((m1, v1))
    return {"points": out, "filled": filled, "gaps": gaps}


def last_segment(points: list[tuple[str, float]], max_gap: int = 3) -> list[tuple[str, float]]:
    """The most recent gap-free monthly run of :func:`regularize` (filled months included)."""
    reg = regularize(points, max_gap)["points"]
    seg: list[tuple[str, float]] = []
    for m, v in reversed(reg):
        if v is None:
            break
        seg.append((m, v))
    return seg[::-1]
