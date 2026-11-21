"""Forecast fan: p10/p50/p90 per month from the weighted ensemble plus out-of-sample errors.

Centre: every model is fitted on the whole gap-free run (≤ ``as_of``) and the log forecasts are combined with the
weights for that month's anchor horizon. Spread: for month h the anchor is the smallest backtested horizon ≥ h that
has errors (else the largest that has); ``n`` draws are bootstrapped from the ensemble's out-of-sample errors at that
anchor (:func:`vnrealty.forecast.backtest.ensemble_errors`) and scaled by √(h / anchor) (random-walk scaling).
level = centre × exp(−e), since e = ln(forecast / actual) — a model that over-forecast in the backtest is pulled down
here by its own record. The fan only widens: each month's p50−p10 and p90−p50 (in logs) are at least the previous
month's. Deterministic per ``seed``.

Units: levels in the series unit; ``mult*`` = level ÷ the last observed level (a multiplier on today's area price).
"""
from __future__ import annotations

import math
import random
from typing import Callable

from vnrealty.forecast.backtest import ensemble_errors, ensemble_weights, walk_forward
from vnrealty.forecast.models import Fitted, prepare
from vnrealty.forecast.series import month_add
from vnrealty.stats import quantile
from vnrealty.types import Insufficient

__all__ = ["fan"]


def fan(series: list[tuple[str, float]], models: list[tuple[str, Callable]], weights: dict[str, float] | None,
        h: int, n: int = 2000, seed: int = 7, results: dict | None = None, as_of: str | None = None,
        min_train: int = 24, horizons: tuple[int, ...] = (3, 6, 12, 24)) -> dict | Insufficient:
    """Fan for months 1..``h`` after the last observed month.

    ``weights`` fixed per model, or None to use :func:`ensemble_weights` at each month's anchor horizon. ``results``
    is a :func:`walk_forward` output (run here when None). Returns ``{last_month, last_value, months, horizons, p10,
    p50, p90, mult10, mult50, mult90, anchor, weights, n_errors, n, seed}``. ``Insufficient`` when the backtest is
    too short or no model fits.
    """
    seg = prepare(series, as_of)
    if results is None:
        results = walk_forward(series, models, min_train=min_train, horizons=horizons, as_of=as_of)
    if isinstance(results, Insufficient):
        return Insufficient("fan", results.reason, results.detail)
    fitted = {}
    for name, fit in models:
        f = fit(seg, seg[-1][0])
        if isinstance(f, Fitted):
            fitted[name] = f
    if not fitted:
        return Insufficient("fan", "no model could be fitted on the full run")
    hs = sorted(k for k in {hh for v in results["models"].values() for hh in v} if any(
        results["models"][m].get(k, {}).get("n") for m in fitted))
    if not hs:
        return Insufficient("fan", "no out-of-sample errors for the fitted models")
    paths = {m: f.forecast_log(h) for m, f in fitted.items()}
    rng = random.Random(seed)
    y_last = math.log(seg[-1][1])
    out = {"last_month": seg[-1][0], "last_value": seg[-1][1], "months": [], "horizons": [], "p10": [], "p50": [],
           "p90": [], "mult10": [], "mult50": [], "mult90": [], "anchor": [], "weights": {}, "n_errors": {}, "n": n,
           "seed": seed}
    lo_w = hi_w = 0.0
    cache: dict[int, tuple[dict, list[float]]] = {}
    for k in range(1, h + 1):
        a = next((x for x in hs if x >= k), hs[-1])
        if a not in cache:
            w = weights if weights is not None else ensemble_weights(results, a)
            if isinstance(w, Insufficient):
                return Insufficient("fan", w.reason)
            w = {m: v for m, v in w.items() if m in fitted and v > 0}
            if not w:
                return Insufficient("fan", f"no weighted model is fitted at anchor horizon {a}")
            s = sum(w.values())
            w = {m: v / s for m, v in w.items()}
            cache[a] = (w, ensemble_errors(results, a, w))
        w, errs = cache[a]
        if not errs:
            return Insufficient("fan", f"weighted models share no out-of-sample origin at horizon {a}")
        centre = sum(w[m] * paths[m][k - 1] for m in w)
        sc = math.sqrt(k / a)
        draws = [centre - sc * errs[rng.randrange(len(errs))] for _ in range(n)]
        q10, q50, q90 = quantile(draws, 0.1), quantile(draws, 0.5), quantile(draws, 0.9)
        lo_w, hi_w = max(lo_w, q50 - q10), max(hi_w, q90 - q50)
        q10, q90 = q50 - lo_w, q50 + hi_w
        out["months"].append(month_add(seg[-1][0], k))
        out["horizons"].append(k)
        out["anchor"].append(a)
        for key, q in (("p10", q10), ("p50", q50), ("p90", q90)):
            out[key].append(math.exp(q))
            out["mult" + key[1:]].append(math.exp(q - y_last))
        out["weights"][a] = w
        out["n_errors"][a] = len(errs)
    return out
