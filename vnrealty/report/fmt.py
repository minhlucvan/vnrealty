"""Formatting numbers for reports: VND in B/M, percentages, dates. Display only — never used in arithmetic."""
from __future__ import annotations

import math

__all__ = ["vnd", "pct", "num", "signed"]


def _bad(v) -> bool:
    return v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def vnd(v: float | None, d: int | None = None) -> str:
    """3.25e9 → '3.25B', 45e6 → '45M', 850e3 → '850K'. '—' for missing."""
    if _bad(v):
        return "—"
    a, s = abs(v), "−" if v < 0 else ""
    if a >= 1e9:
        return f"{s}{a / 1e9:.{2 if d is None else d}f}B"
    if a >= 1e6:
        return f"{s}{a / 1e6:.{(1 if a < 1e7 else 0) if d is None else d}f}M"
    if a >= 1e3:
        return f"{s}{a / 1e3:.0f}K"
    return f"{s}{a:.0f}"


def pct(v: float | None, d: int = 1) -> str:
    return "—" if _bad(v) else f"{v * 100:.{d}f}%"


def num(v: float | None, d: int = 2) -> str:
    return "—" if _bad(v) else f"{v:,.{d}f}"


def signed(v: float | None, f=vnd) -> dict:
    """A cell coloured by sign: {'v': text, 'cls': 'pos'|'neg'|''}."""
    if _bad(v):
        return {"v": "—", "cls": ""}
    return {"v": f(v), "cls": "pos" if v > 0 else "neg" if v < 0 else ""}
