"""Forecast models on monthly log index levels. Each ``fit_*`` is point in time and deterministic.

Every model fits ``y_t = ln(level_t)`` on the most recent gap-free run of the series up to ``as_of``
(:func:`vnrealty.forecast.series.last_segment`, gaps ≤ 3 months log-interpolated) and returns a :class:`Fitted`
whose ``forecast(h)`` is the point path for the next ``h`` months, or an ``Insufficient`` saying how many months it
needs.

* **rw_drift** — random walk with drift. drift = λ·mean(Δy over the last ``window`` months) + (1 − λ)·prior,
  λ = n / (n + ``shrink_months``). prior = ln(1 + ``prior_annual``)/12 when given, else the mean Δy of the whole
  run (so with no stated prior the shrinkage is toward the series' own long-run growth). Needs 13 months.
* **local_trend** — Holt's linear trend with damping φ on y: level ℓ, trend b; ŷ(t+h) = ℓ + (φ + … + φʰ)·b.
  (α, β, φ) chosen by grid search on the in-sample one-step squared error. Needs 12 months.
* **ar_growth** — AR(1) on 12-month log growth g_t = y_t − y_{t−12}, mean-reverting to μ:
  g_{t+1} − μ = ρ(g_t − μ) + ε, ρ by least squares through the origin, clamped to [0, 0.99]; μ = ln(1 + prior_annual)
  or the run's mean g. The path adds g_{t+k}/12 per month. Needs 30 months.
* **driver_regression** — monthly Δy_t = a + Σ bⱼ·xⱼ(t − ``lag``) by OLS on aligned months (drivers such as mortgage
  rate change, credit growth, new-listing growth, price-cut rate, passed in as monthly series). Beyond ``lag``
  months the drivers are unknown, so each is set to its training mean (a neutral assumption, recorded).
  ``Insufficient`` with fewer than ``min_points`` aligned months (default 24).

Units: levels in the series unit; Δy and drift in log points per month; ``prior_annual`` a fraction per year.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import partial
from typing import Callable

from vnrealty.forecast.series import last_segment, month_add
from vnrealty.stats import ols
from vnrealty.types import Insufficient

__all__ = ["Fitted", "fit_rw_drift", "fit_local_trend", "fit_ar_growth", "fit_driver_regression", "default_models",
           "MIN_MONTHS", "prepare"]

MIN_MONTHS = {"rw_drift": 13, "local_trend": 12, "ar_growth": 30, "driver_regression": 24}


@dataclass
class Fitted:
    """A fitted model. ``forecast(h)`` → ``[(YYYY-MM, level)]`` for months 1..h after ``last_month``."""
    name: str
    last_month: str
    y_last: float
    n: int
    params: dict
    resid: list[float]                       # in-sample one-step log errors (actual − fitted)
    _path: Callable[[int], list[float]] = field(repr=False)

    def forecast_log(self, h: int) -> list[float]:
        """Log levels for months 1..h ahead."""
        return self._path(h) if h > 0 else []

    def forecast(self, h: int) -> list[tuple[str, float]]:
        """Levels (series unit) for months 1..h ahead."""
        return [(month_add(self.last_month, k + 1), math.exp(v)) for k, v in enumerate(self.forecast_log(h))]


def prepare(series: list[tuple[str, float]], as_of: str | None = None) -> list[tuple[str, float]]:
    """Point-in-time cut (months ≤ ``as_of``'s month) of the series, then its most recent gap-free run."""
    pts = [(m, v) for m, v in series if v is not None and v > 0 and (as_of is None or m <= as_of[:7])]
    return last_segment(pts)


def _need(name: str, n: int, need: int) -> Insufficient:
    return Insufficient(name, f"needs {need} gap-free months, has {n}", {"months_needed": need - n})


def _logs(seg):
    return [math.log(v) for _, v in seg]


def fit_rw_drift(series: list[tuple[str, float]], as_of: str | None = None, prior_annual: float | None = None,
                 window: int = 36, shrink_months: float = 24.0) -> Fitted | Insufficient:
    """Random walk with shrunk drift (see module doc)."""
    seg = prepare(series, as_of)
    if len(seg) < MIN_MONTHS["rw_drift"]:
        return _need("rw_drift", len(seg), MIN_MONTHS["rw_drift"])
    y = _logs(seg)
    d = [b - a for a, b in zip(y, y[1:])]
    recent = d[-window:]
    prior = math.log(1 + prior_annual) / 12 if prior_annual is not None else sum(d) / len(d)
    lam = len(recent) / (len(recent) + shrink_months)
    drift = lam * sum(recent) / len(recent) + (1 - lam) * prior
    resid = [x - drift for x in d]
    yl = y[-1]
    return Fitted("rw_drift", seg[-1][0], yl, len(seg),
                  {"drift_month": drift, "drift_annual": math.exp(12 * drift) - 1, "lambda": lam,
                   "prior_month": prior, "prior_source": "stated" if prior_annual is not None else "run mean"},
                  resid, lambda h: [yl + drift * (k + 1) for k in range(h)])


def _holt(y: list[float], a: float, b: float, phi: float) -> tuple[float, float, float, list[float]]:
    lvl, tr = y[0], y[1] - y[0]
    sse, res = 0.0, []
    for t in range(1, len(y)):
        f = lvl + phi * tr
        e = y[t] - f
        if t >= 2:
            sse += e * e
            res.append(e)
        new = f + a * e
        tr = phi * tr + a * b * e
        lvl = new
    return lvl, tr, sse, res


def fit_local_trend(series: list[tuple[str, float]], as_of: str | None = None,
                    alphas: tuple = (0.2, 0.4, 0.6, 0.8, 1.0), betas: tuple = (0.05, 0.1, 0.2, 0.4),
                    phis: tuple = (0.8, 0.9, 0.98)) -> Fitted | Insufficient:
    """Damped Holt on log levels; (α, β, φ) by grid search on in-sample one-step SSE (ties → first in grid order)."""
    seg = prepare(series, as_of)
    if len(seg) < MIN_MONTHS["local_trend"]:
        return _need("local_trend", len(seg), MIN_MONTHS["local_trend"])
    y = _logs(seg)
    best = None
    for a in alphas:
        for b in betas:
            for p in phis:
                lvl, tr, sse, res = _holt(y, a, b, p)
                if best is None or sse < best[0] - 1e-15:
                    best = (sse, a, b, p, lvl, tr, res)
    sse, a, b, p, lvl, tr, res = best

    def path(h: int) -> list[float]:
        out, acc, ph = [], 0.0, 1.0
        for _ in range(h):
            ph *= p
            acc += ph
            out.append(lvl + acc * tr)
        return out

    return Fitted("local_trend", seg[-1][0], y[-1], len(seg),
                  {"alpha": a, "beta": b, "phi": p, "level": lvl, "trend_month": tr, "sse": sse}, res, path)


def fit_ar_growth(series: list[tuple[str, float]], as_of: str | None = None,
                  prior_annual: float | None = None) -> Fitted | Insufficient:
    """AR(1) on 12-month log growth reverting to μ (see module doc)."""
    seg = prepare(series, as_of)
    if len(seg) < MIN_MONTHS["ar_growth"]:
        return _need("ar_growth", len(seg), MIN_MONTHS["ar_growth"])
    y = _logs(seg)
    g = [y[t] - y[t - 12] for t in range(12, len(y))]
    mu = math.log(1 + prior_annual) if prior_annual is not None else sum(g) / len(g)
    x = [v - mu for v in g]
    den = sum(v * v for v in x[:-1])
    rho = sum(a * b for a, b in zip(x, x[1:])) / den if den > 0 else 0.0
    rho = max(0.0, min(0.99, rho))
    # one-step level errors: actual Δy_t − the model's predicted step (μ + ρ(g_{t−1} − μ))/12
    resid = [(y[t] - y[t - 1]) - (mu + rho * (y[t - 1] - y[t - 13] - mu)) / 12 for t in range(13, len(y))]
    yl, gl = y[-1], g[-1]

    def path(h: int) -> list[float]:
        out, lv = [], yl
        for k in range(1, h + 1):
            lv += (mu + rho ** k * (gl - mu)) / 12
            out.append(lv)
        return out

    return Fitted("ar_growth", seg[-1][0], yl, len(seg),
                  {"rho": rho, "mu_annual_log": mu, "g12_last": gl,
                   "mu_source": "stated" if prior_annual is not None else "run mean"},
                  resid, path)


def fit_driver_regression(series: list[tuple[str, float]], as_of: str | None = None,
                          drivers: dict[str, list[tuple[str, float]]] | None = None, lag: int = 3,
                          min_points: int = 24) -> Fitted | Insufficient:
    """Monthly log growth on lagged drivers (see module doc). Driver months after ``as_of`` are never used."""
    if not drivers:
        return Insufficient("driver_regression", "no drivers given")
    seg = prepare(series, as_of)
    cut = as_of[:7] if as_of else None
    dv = {k: {m: float(v) for m, v in pts if v is not None and (cut is None or m <= cut)} for k, pts in drivers.items()}
    names = sorted(dv)
    y = dict(zip([m for m, _ in seg], _logs(seg)))
    months = [m for m, _ in seg]
    X, Y, used = [], [], []
    for m0, m1 in zip(months, months[1:]):
        src = month_add(m1, -lag)
        if all(src in dv[k] for k in names):
            X.append([1.0] + [dv[k][src] for k in names])
            Y.append(y[m1] - y[m0])
            used.append(m1)
    if len(Y) < min_points:
        return Insufficient("driver_regression", f"needs {min_points} aligned months, has {len(Y)}",
                            {"months_needed": min_points - len(Y), "drivers": names, "lag": lag})
    fit = ols(X, Y, ["const"] + names)
    if fit is None:
        return Insufficient("driver_regression", "singular design (constant or collinear drivers)", {"drivers": names})
    means = {k: sum(r[i + 1] for r in X) / len(X) for i, k in enumerate(names)}
    resid = [yy - fit.predict(xx) for xx, yy in zip(X, Y)]
    last = months[-1]
    yl = y[last]

    def path(h: int) -> list[float]:
        out, lv = [], yl
        for k in range(1, h + 1):
            src = month_add(last, k - lag)
            xs = [1.0] + [dv[n].get(src, means[n]) if k <= lag else means[n] for n in names]
            lv += fit.predict(xs)
            out.append(lv)
        return out

    return Fitted("driver_regression", last, yl, len(seg),
                  {"coef": fit.coef(), "r2": fit.r2, "sigma": fit.sigma, "n_aligned": len(Y), "lag": lag,
                   "beyond_lag": "drivers held at training mean"}, resid, path)


def default_models(prior_annual: float | None = None, drivers: dict | None = None,
                   lag: int = 3) -> list[tuple[str, Callable]]:
    """The standard model set as ``[(name, fit(series, as_of))]``; driver_regression only when drivers are given."""
    ms = [("rw_drift", partial(fit_rw_drift, prior_annual=prior_annual)),
          ("local_trend", fit_local_trend),
          ("ar_growth", partial(fit_ar_growth, prior_annual=prior_annual))]
    if drivers:
        ms.append(("driver_regression", partial(fit_driver_regression, drivers=drivers, lag=lag)))
    return ms
