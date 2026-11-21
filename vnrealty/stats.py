"""Small, tested statistics for the desk — stdlib only.

quantile / median / iqr, weighted_median, mad, ols (normal equations with ridge-free Gauss-Jordan and the
residual standard error), bootstrap_ci with a fixed seed so results are reproducible.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Sequence

__all__ = ["quantile", "median", "iqr", "weighted_median", "mad", "ols", "OLSResult", "bootstrap_ci", "solve"]


def quantile(xs: Sequence[float], q: float) -> float | None:
    """Linear-interpolated quantile (type 7). None for an empty input."""
    a = sorted(x for x in xs if x is not None and not math.isnan(x))
    if not a:
        return None
    if len(a) == 1:
        return a[0]
    h = (len(a) - 1) * q
    lo = math.floor(h)
    return a[lo] + (a[min(lo + 1, len(a) - 1)] - a[lo]) * (h - lo)


def median(xs: Sequence[float]) -> float | None:
    return quantile(xs, 0.5)


def iqr(xs: Sequence[float]) -> tuple[float, float] | None:
    lo, hi = quantile(xs, 0.25), quantile(xs, 0.75)
    return None if lo is None else (lo, hi)


def weighted_median(xs: Sequence[float], ws: Sequence[float]) -> float | None:
    pairs = sorted((x, w) for x, w in zip(xs, ws) if w > 0)
    if not pairs:
        return None
    half, acc = sum(w for _, w in pairs) / 2, 0.0
    for x, w in pairs:
        acc += w
        if acc >= half:
            return x
    return pairs[-1][0]


def mad(xs: Sequence[float]) -> float | None:
    m = median(xs)
    return None if m is None else median([abs(x - m) for x in xs])


def solve(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Gauss-Jordan with partial pivoting. None when singular."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-12:
            return None
        M[c], M[p] = M[p], M[c]
        piv = M[c][c]
        M[c] = [v / piv for v in M[c]]
        for r in range(n):
            if r != c and M[r][c] != 0:
                f = M[r][c]
                M[r] = [rv - f * cv for rv, cv in zip(M[r], M[c])]
    return [M[i][n] for i in range(n)]


class OLSResult:
    def __init__(self, beta: list[float], names: list[str], sigma: float, r2: float, n: int, k: int):
        self.beta, self.names, self.sigma, self.r2, self.n, self.k = beta, names, sigma, r2, n, k

    def coef(self) -> dict[str, float]:
        return dict(zip(self.names, self.beta))

    def predict(self, x: Sequence[float]) -> float:
        return sum(b * v for b, v in zip(self.beta, x))


def ols(X: list[list[float]], y: list[float], names: list[str] | None = None) -> OLSResult | None:
    """Least squares via normal equations. X should include an intercept column if wanted.
    Returns None when the design is singular or there are not more rows than columns."""
    n, k = len(X), len(X[0]) if X else 0
    if n <= k or k == 0:
        return None
    XtX = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(k)] for i in range(k)]
    Xty = [sum(X[r][i] * y[r] for r in range(n)) for i in range(k)]
    beta = solve(XtX, Xty)
    if beta is None:
        return None
    res = [y[r] - sum(beta[i] * X[r][i] for i in range(k)) for r in range(n)]
    ss_res = sum(e * e for e in res)
    ybar = sum(y) / n
    ss_tot = sum((v - ybar) ** 2 for v in y)
    return OLSResult(beta, names or [f"x{i}" for i in range(k)], math.sqrt(ss_res / (n - k)), 1 - ss_res / ss_tot if ss_tot > 0 else 0.0, n, k)


def bootstrap_ci(xs: Sequence[float], stat: Callable[[Sequence[float]], float], n: int = 500, alpha: float = 0.2,
                 seed: int = 7) -> tuple[float, float] | None:
    """Percentile bootstrap interval (default 80%). Deterministic for a given seed."""
    xs = list(xs)
    if len(xs) < 2:
        return None
    rng = random.Random(seed)
    vals = sorted(stat([xs[rng.randrange(len(xs))] for _ in xs]) for _ in range(n))
    return quantile(vals, alpha / 2), quantile(vals, 1 - alpha / 2)
