"""Injectable browser extractors — bundling and capture saving.

The scripts in ``browser/`` run in the investor's own Chrome through the claude-in-chrome ``javascript_tool``. Each
bundle is ``(() => { <lib/core.js> <site body> })()`` — one expression whose value is the capture envelope
``{site, url, seen_at, kind, items, warnings}``. Scripts are read-only (no network, clicks or submits) and never return
phone numbers (``phone_hash`` only). Numbers stay raw text; ``vnrealty.listings.parse`` is the one parser.

Usage from an agent: ``javascript_tool(text=script('batdongsan'))`` → JSON → ``save_capture(obj, 'data')`` →
``vnr`` ingest of ``data/raw/<site>/<date>/<slug>.json``.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

__all__ = ["BROWSER_DIR", "script", "list_scripts", "save_capture", "save_text_capture", "capture_path",
           "is_self_contained"]

BROWSER_DIR = Path(__file__).resolve().parents[1] / "browser"


def list_scripts() -> list[str]:
    """Names of the bundled extractors (file stems in ``browser/``, excluding ``lib/``)."""
    return sorted(p.stem for p in BROWSER_DIR.glob("*.js"))


def script(name: str) -> str:
    """The bundled JS (core + site body) for ``name`` as one evaluable expression. KeyError for an unknown name."""
    body = BROWSER_DIR / f"{name}.js"
    if name not in list_scripts():
        raise KeyError(f"no browser script {name!r}; have {list_scripts()}")
    src = body.read_text(encoding="utf-8")
    if is_self_contained(src):
        return src.strip()
    core = (BROWSER_DIR / "lib" / "core.js").read_text(encoding="utf-8")
    return "(() => {\n" + core + "\n/* ---- " + name + ".js ---- */\n" + src + "\n})()"


def is_self_contained(src: str) -> bool:
    """True for a script that is already one IIFE expression (after leading comments) and needs no core bundling."""
    code = re.sub(r"^\s*(?:/\*.*?\*/\s*|//[^\n]*\n\s*)*", "", src, flags=re.S)
    return code.startswith("(() =>") or code.startswith("(function")


def _slug(s: str, n: int = 60) -> str:
    s = re.sub(r"^https?://", "", s or "")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:n] or "capture"


def capture_path(site: str, seen_at: str, url: str | None, data_dir: str | Path, ext: str = "json") -> Path:
    """``<data_dir>/raw/<site>/<YYYY-MM-DD>/<slug>-<hash8>.<ext>`` — the hash keeps two captures of one URL apart."""
    date = (seen_at or "")[:10] or "undated"
    tail = hashlib.sha1(f"{url}|{seen_at}".encode()).hexdigest()[:8]
    return Path(data_dir) / "raw" / _slug(site, 30) / date / f"{_slug(url or site)}-{tail}.{ext}"


def save_capture(obj: dict, data_dir: str | Path) -> Path:
    """Write a script's capture to ``data/raw/<site>/<date>/<slug>.json`` and return the path.

    Accepts the envelope as a dict or as the JSON string a script returned (batdongsan.js returns
    ``JSON.stringify(env)`` with ``kind: 'srp'``, ``columns`` and compact row arrays). A ``#total=…`` string from
    nhatot.js (pipe-separated rows) is saved verbatim as ``.txt``. Raises ValueError when an envelope lacks
    ``site``/``seen_at``/``kind``/``items``."""
    if isinstance(obj, str):
        if obj.startswith("#total="):                       # nhatot.js compact rows: saved verbatim as .txt
            head = dict(kv.split("=", 1) for kv in obj.splitlines()[0][1:].split("|") if "=" in kv)
            p = capture_path("chotot", head.get("seen_at", ""), head.get("url"), data_dir, "txt")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(obj, encoding="utf-8")
            return p
        obj = json.loads(obj)
    missing = [k for k in ("site", "seen_at", "kind", "items") if k not in obj]
    if missing:
        raise ValueError(f"capture missing {missing}")
    p = capture_path(obj["site"], obj["seen_at"], obj.get("url"), data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def save_text_capture(headers: dict, text: str, data_dir: str | Path) -> Path:
    """Write a text capture (``# key: value`` headers, blank line, page text) with phone numbers redacted."""
    from vnrealty.listings.parse import redact_phones

    for k in ("url", "site", "seen_at", "kind"):
        if not headers.get(k):
            raise ValueError(f"text capture needs header {k!r}")
    p = capture_path(headers["site"], headers["seen_at"], headers["url"], data_dir, "txt")
    p.parent.mkdir(parents=True, exist_ok=True)
    head = "".join(f"# {k}: {v}\n" for k, v in headers.items() if v is not None)
    p.write_text(head + "\n" + redact_phones(text), encoding="utf-8")
    return p
