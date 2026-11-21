"""Plumbing shared by every CLI command: JSON-safe serialisation, the human table printer, JSON input loading,
guarded imports of modules other builders are still writing, and SUBJECT resolution.

Display formatting goes through :mod:`vnrealty.report.fmt`; it never feeds arithmetic.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import importlib
import inspect
import json
import math
import re
import sqlite3
from pathlib import Path

from vnrealty.report import fmt
from vnrealty.types import Estimate, Insufficient

__all__ = ["Unavailable", "CliError", "jsonable", "status_of", "load_json", "guarded", "call_flex", "today",
           "now_ts", "resolve_subject", "subject_key", "print_human", "money_key", "rate_key"]


class Unavailable(Exception):
    """A module or function the command needs does not exist (yet). Exit 2 with ``status: unavailable``."""


class CliError(Exception):
    """A user error (bad file, unknown id, malformed flag). Exit 1 with ``status: error``."""


# ------------------------------------------------------------------ serialisation

def jsonable(o):
    """Library results → plain JSON: dataclasses → dicts (Estimate/Insufficient gain ``status``), tuples → lists,
    Paths → str, NaN/inf → None. Floats are left raw."""
    if isinstance(o, Estimate):
        d = {k: jsonable(v) for k, v in dataclasses.asdict(o).items()}
        d["status"] = "ok"
        return d
    if isinstance(o, Insufficient):
        d = {k: jsonable(v) for k, v in dataclasses.asdict(o).items()}
        d["status"] = "insufficient"
        return d
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: jsonable(getattr(o, f.name)) for f in dataclasses.fields(o) if not f.name.startswith("_")}
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [jsonable(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, sqlite3.Row):
        return dict(o)
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    if callable(o):
        return None
    return str(o)


def status_of(x) -> str:
    """'insufficient' for an Insufficient, else 'ok'."""
    return "insufficient" if isinstance(x, Insufficient) else "ok"


# ------------------------------------------------------------------ inputs

def load_json(src: str | None, what: str = "JSON"):
    """A JSON value from a file path, or from an inline JSON string (starts with ``{`` or ``[``)."""
    if src is None:
        return None
    s = src.strip()
    if s[:1] in "{[":
        try:
            return json.loads(s)
        except ValueError as e:
            raise CliError(f"{what}: invalid inline JSON ({e})")
    p = Path(src)
    if not p.exists():
        raise CliError(f"{what}: no such file {src}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise CliError(f"{what}: {src} is not valid JSON ({e})")


def guarded(module: str, *names: str):
    """Import ``module`` and return the first attribute in ``names`` that exists (or the module when no names).
    Raises :class:`Unavailable` naming what is missing — never a stand-in implementation."""
    try:
        mod = importlib.import_module(module)
    except ImportError as e:
        raise Unavailable(f"{module} is not available ({e})")
    if not names:
        return mod
    for n in names:
        f = getattr(mod, n, None)
        if f is not None:
            return f
    raise Unavailable(f"{module} has none of {', '.join(names)}")


def call_flex(fn, *args, **kw):
    """Call ``fn`` passing only the keyword arguments its signature accepts (for modules still being written)."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(*args, **kw)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        return fn(*args, **kw)
    return fn(*args, **{k: v for k, v in kw.items() if k in sig.parameters})


def today() -> str:
    return _dt.date.today().isoformat()


def now_ts() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


# ------------------------------------------------------------------ subjects

_ATTRS = ("ptype", "ward_code", "lat", "lng", "area_m2", "frontage_m", "alley_m", "corner", "legal", "street")


def _bool(v):
    return None if v is None else bool(v)


def _listing_subject(con, lid: int, as_of: str) -> dict:
    r = con.execute("SELECT * FROM listing WHERE id = ?", (lid,)).fetchone()
    if r is None:
        raise CliError(f"no listing {lid}")
    r = dict(r)
    end = as_of if len(as_of) > 10 else as_of + "T99"
    kinds = ("rent",) if r["deal"] == "rent" else ("asking", "sale")
    ob = con.execute(
        f"SELECT price, seen_at, url, kind, site FROM listing_obs WHERE listing_id = ? AND price IS NOT NULL "
        f"AND seen_at <= ? AND kind IN ({','.join('?' * len(kinds))}) ORDER BY seen_at DESC LIMIT 1",
        (lid, end, *kinds)).fetchone()
    s = {"subject": f"listing:{lid}", "source": "listing", "listing_id": lid, "deal": r["deal"],
         "title": r["title"], "address": r["address"], "status": r["status"]}
    for a in _ATTRS:
        s[a] = _bool(r[a]) if a == "corner" else r.get(a)
    s["ask"] = ob["price"] if ob else None
    s["ask_kind"] = ob["kind"] if ob else None
    s["ask_seen_at"] = ob["seen_at"] if ob else None
    s["url"] = ob["url"] if ob else None
    return s


def _unit_subject(con, uid: str, as_of: str) -> dict:
    r = con.execute("SELECT * FROM unit WHERE id = ?", (uid,)).fetchone()
    if r is None:
        raise CliError(f"no unit {uid}")
    r = dict(r)
    s = {"subject": f"unit:{uid}", "source": "unit", "unit_id": uid, "name": r["name"], "address": r["address"],
         "cost": r["cost"], "bought_at": r["bought_at"], "share": r["share"], "value": r["value"],
         "value_at": r["value_at"], "listing_id": r["listing_id"], "deal": "sale", "ask": None}
    for a in _ATTRS:
        s[a] = r.get(a)
    m = re.search(r"\baccess:(kiet|street)\b", r.get("notes") or "")   # note-token convention, like zoning:<code>
    if m:
        s["access"] = m.group(1)
    if r.get("listing_id"):
        try:
            ls = _listing_subject(con, int(r["listing_id"]), as_of)
            for a in _ATTRS:
                if s.get(a) is None:
                    s[a] = ls.get(a)
        except CliError:
            pass
    return s


def _lot_subject(path: Path) -> dict:
    d = load_json(str(path), "lot")
    if not isinstance(d, dict):
        raise CliError(f"{path}: a lot file must be a JSON object")
    s = {a: d.get(a) for a in _ATTRS}
    if s["ward_code"] is None and d.get("ward"):
        from vnrealty.geo.wards import load_wards, match_ward
        codes = {w["code"] for w in load_wards()}
        s["ward_code"] = d["ward"] if d["ward"] in codes else match_ward(d["ward"])
    s.update({k: v for k, v in d.items() if k not in s})
    s["subject"] = d.get("subject") or f"lot:{d.get('name') or path.stem}"
    s["source"] = "lot"
    s.setdefault("ask", d.get("price"))
    s.setdefault("deal", "sale")
    return s


def resolve_subject(con, text: str, as_of: str) -> dict:
    """``listing:<id>`` or a bare integer → the listing (latest priced observation ≤ as_of = ``ask``);
    ``unit:<id>`` → the unit; a path to a JSON file → the lot dict. Missing attributes stay None."""
    t = str(text).strip()
    if re.fullmatch(r"\d+", t):
        return _listing_subject(con, int(t), as_of)
    if t.startswith("listing:"):
        try:
            return _listing_subject(con, int(t.split(":", 1)[1]), as_of)
        except ValueError:
            raise CliError(f"bad listing id in {t!r}")
    if t.startswith("unit:"):
        return _unit_subject(con, t.split(":", 1)[1], as_of)
    p = Path(t)
    if p.suffix.lower() == ".json" or p.exists():
        if not p.exists():
            raise CliError(f"no such lot file {t}")
        return _lot_subject(p)
    raise CliError(f"cannot resolve subject {t!r}: use listing:<id>, <id>, unit:<id> or a lot .json file")


def subject_key(text: str) -> str:
    """The calibration / ledger key for a SUBJECT argument without touching the DB (bare int → listing:<id>)."""
    t = str(text).strip()
    if re.fullmatch(r"\d+", t):
        return f"listing:{t}"
    if t.startswith(("listing:", "unit:", "lot:")):
        return t
    return f"lot:{Path(t).stem}"


# ------------------------------------------------------------------ human output

_MONEY = re.compile(r"(^|_)(price|value|lo|hi|cost|npv|profit|cash|rent|loan|debt|equity|noi|vnd|amount|income|"
                    r"spend|budget|take_home|deposit|edge|p10|p50|p90|mean|ask|median_rent|sale_net|fee|tax|total|"
                    r"swing|peak_cash|ev_npv|bear_loss|expected_npv|expected_profit|balance|interest|opex|"
                    r"debt_service|collected|expected|paid|arrears|net|max_price|loan_max|from|to|est_value|"
                    r"service|payment|w|renovation|running_costs|staff|build_cost|p25|p75)($|_)")
_RATE = re.compile(r"(^|_)(irr|yield|pct|rate|gap|ltv|ltc|vacancy|share|coverage|mape|bias|p_loss|p|growth|cut_rate|"
                   r"weight|dti|occupancy|hurdle|cash_on_cash|uplift|p_done|residual|buy_costs|sell_costs|management|cogs|"
                   r"rent_tax|business_tax)($|_)")
_PM2 = re.compile(r"(^|_)(m2|ppm2|median|q1|q3|iqr)($|_)")


def money_key(k: str) -> bool:
    return bool(_MONEY.search(k)) and not _RATE.search(k) and not k.endswith(("_m", "_km", "_months", "month"))


def rate_key(k: str) -> bool:
    return bool(_RATE.search(k)) and not k.endswith(("_id", "_months"))


def _cell(k: str, v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        if rate_key(k) and abs(v) <= 10:
            return fmt.pct(v)
        if money_key(k) or (_PM2.search(k) and abs(v) >= 1e4):
            return fmt.vnd(v)
        if isinstance(v, float):
            return fmt.num(v, 2 if abs(v) < 1000 else 0)
        return str(v)
    if isinstance(v, dict):
        if v.get("status") == "insufficient":
            return "insufficient: " + str(v.get("reason", ""))[:60]
        if "value" in v and isinstance(v.get("value"), (int, float)):
            return fmt.vnd(v["value"])
        return json.dumps(v, ensure_ascii=False, default=str)[:60]
    if isinstance(v, list):
        return ", ".join(str(x) for x in v[:6])[:60] + ("…" if len(v) > 6 else "")
    s = str(v)
    return s if len(s) <= 60 else s[:57] + "…"


def _table(rows: list[dict], max_rows: int = 40, max_cols: int = 10) -> list[str]:
    cols: list[str] = []
    for r in rows[:max_rows]:
        for k, v in r.items():
            if k not in cols and not isinstance(v, (list, dict)) or (k not in cols and isinstance(v, dict)
                                                                       and v.get("status")):
                if k not in cols:
                    cols.append(k)
    cols = cols[:max_cols]
    body = [[_cell(c, r.get(c)) for c in cols] for r in rows[:max_rows]]
    w = [max(len(c), *(len(b[i]) for b in body)) if body else len(c) for i, c in enumerate(cols)]
    out = ["  ".join(c.ljust(w[i]) for i, c in enumerate(cols)), "  ".join("-" * x for x in w)]
    out += ["  ".join(b[i].rjust(w[i]) if b[i][:1].isdigit() or b[i][:1] in "−-" else b[i].ljust(w[i])
                      for i in range(len(cols))) for b in body]
    if len(rows) > max_rows:
        out.append(f"… {len(rows) - max_rows} more rows (use --json)")
    return out


def _lines(obj, indent: int = 0, depth: int = 0) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        scal = [(k, v) for k, v in obj.items() if not isinstance(v, (dict, list)) or
                (isinstance(v, dict) and v.get("status") == "insufficient" and depth > 0)]
        if scal:
            w = max(len(k) for k, _ in scal)
            out += [f"{pad}{k.ljust(w)}  {_cell(k, v)}" for k, v in scal]
        for k, v in obj.items():
            if isinstance(v, dict) and not (v.get("status") == "insufficient" and depth > 0):
                if depth >= 3:
                    out.append(f"{pad}{k}: {_cell(k, v)}")
                    continue
                out.append(f"{pad}[{k}]")
                out += _lines(v, indent + 1, depth + 1)
            elif isinstance(v, list):
                if not v:
                    out.append(f"{pad}{k}: (none)")
                elif all(isinstance(x, dict) for x in v):
                    out.append(f"{pad}[{k}] ({len(v)})")
                    out += [pad + "  " + line for line in _table(v)]
                else:
                    out.append(f"{pad}{k}: {_cell(k, v)}")
    else:
        out.append(pad + _cell("", obj))
    return out


def print_human(payload: dict, write=print) -> None:
    """Compact, aligned rendering of a command result: scalars first, then nested blocks, lists of dicts as
    tables. VND via fmt.vnd, rates via fmt.pct. Use --json for the exact numbers."""
    for line in _lines(payload):
        write(line)
