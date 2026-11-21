"""Walk-forward backtest of the forecast models and ensemble weights earned from it.

For each origin month i (from the ``min_train``-th month of the gap-free run, every ``step`` months) every model is
fitted on months ≤ i only (point in time) and forecasts ``max(horizons)`` months. For each horizon h with a realised
month i + h the log error e = ln(forecast / actual) is recorded (positive = over-forecast).

Per model and horizon: ``n``, ``mae`` and ``rmse`` of e, ``bias`` = mean e, and ``coverage`` — the share of realised
values inside the model's own 80% residual-bootstrap interval (the h-step sum of resampled in-sample one-step
residuals, ``n_boot`` draws, fixed seed). In-sample residual intervals are usually too narrow; the coverage says by
how much, and :mod:`vnrealty.forecast.fan` therefore uses the out-of-sample errors instead.

Errors at successive origins overlap (a 12-month error shares 11 months with the next), so ``n`` overstates the
independent evidence; :func:`ensemble_weights` shrinks hard for that reason.

Selection rule: always ensemble. Weight ∝ 1 / max(MSE, ``mse_floor``), blended with equal weights:
w = λ·raw + (1 − λ)·equal, λ = n_eff / (n_eff + ``shrink_n``), n_eff = n / h (non-overlapping windows). The single best
model (lowest RMSE) is reported alongside, never used alone.

Units: errors in log points (0.05 ≈ 5%).
"""
from __future__ import annotations

import math
import random
from typing import Callable

from vnrealty.forecast.models import Fitted, prepare
from vnrealty.stats import quantile
from vnrealty.types import Insufficient

__all__ = ["walk_forward", "ensemble_weights", "ensemble_errors", "months_needed"]


def months_needed(min_train: int, horizons: tuple[int, ...]) -> int:
    """Gap-free months needed to score the shortest horizon at least once."""
    return min_train + min(horizons)


def walk_forward(series: list[tuple[str, float]], models: list[tuple[str, Callable]], min_train: int = 24,
                 horizons: tuple[int, ...] = (3, 6, 12, 24), step: int = 1, as_of: str | None = None,
                 n_boot: int = 200, seed: int = 7) -> dict | Insufficient:
    """Per model per horizon out-of-sample scores (see module doc).

    Returns ``{months, first_month, last_month, origins, models: {name: {h: {n, mae, rmse, bias, coverage}}},
    errors: {name: {h: {origin_month: e}}}, insufficient: {name: [reasons]}, horizons_unscored: {h: months_needed},
    best: {h: name}}``. ``Insufficient`` (with ``months_needed``) when the run is too short for even the shortest
    horizon.
    """
    seg = prepare(series, as_of)
    n = len(seg)
    need = months_needed(min_train, horizons)
    if n < need:
        return Insufficient("walk_forward", f"needs {need} gap-free months to backtest, has {n}",
                            {"months_needed": need - n, "months": n})
    hmax = max(horizons)
    rng = random.Random(seed)
    errs: dict[str, dict[int, dict[str, float]]] = {name: {h: {} for h in horizons} for name, _ in models}
    cover: dict[str, dict[int, list[float]]] = {name: {h: [] for h in horizons} for name, _ in models}
    insufficient: dict[str, list[str]] = {}
    origins = 0
    for i in range(min_train - 1, n - min(horizons), step):
        origins += 1
        train = seg[:i + 1]
        for name, fit in models:
            f = fit(train, seg[i][0])
            if not isinstance(f, Fitted):
                r = f.reason
                lst = insufficient.setdefault(name, [])
                if r not in lst:
                    lst.append(r)
                continue
            path = f.forecast_log(min(hmax, n - 1 - i))
            res = f.resid
            for h in horizons:
                if i + h >= n:
                    continue
                e = path[h - 1] - math.log(seg[i + h][1])
                errs[name][h][seg[i][0]] = e
                if len(res) >= 2:
                    sims = sorted(sum(res[rng.randrange(len(res))] for _ in range(h)) for _ in range(n_boot))
                    lo, hi = quantile(sims, 0.1), quantile(sims, 0.9)
                    # actual = forecast × exp(−e); inside [forecast·e^lo, forecast·e^hi] ⇔ −e ∈ [lo, hi]
                    cover[name][h].append(1.0 if lo <= -e <= hi else 0.0)
    scores: dict[str, dict[int, dict]] = {}
    best: dict[int, str] = {}
    for name, _ in models:
        scores[name] = {}
        for h in horizons:
            es = list(errs[name][h].values())
            if not es:
                scores[name][h] = {"n": 0}
                continue
            c = cover[name][h]
            scores[name][h] = {"n": len(es), "mae": sum(abs(e) for e in es) / len(es),
                               "rmse": math.sqrt(sum(e * e for e in es) / len(es)), "bias": sum(es) / len(es),
                               "coverage": sum(c) / len(c) if c else None}
    for h in horizons:
        cands = [(scores[m][h]["rmse"], m) for m, _ in models if scores[m][h]["n"]]
        if cands:
            best[h] = min(cands)[1]
    return {"months": n, "first_month": seg[0][0], "last_month": seg[-1][0], "origins": origins, "min_train": min_train,
            "models": scores, "errors": errs, "insufficient": insufficient, "best": best,
            "horizons_unscored": {h: min_train + h - n for h in horizons if min_train + h > n}}


def ensemble_weights(results: dict, horizon: int, shrink_n: float = 6.0, mse_floor: float = 1e-5) -> dict | Insufficient:
    """Weights (sum 1) per model at ``horizon`` from ``results['models'][name][horizon]`` (``n`` and ``rmse``).

    Works on :func:`walk_forward` output and on :func:`vnrealty.forecast.record.grade` output alike. Models with no
    scored error at that horizon get no weight. ``Insufficient`` when no model has one.
    """
    if isinstance(results, Insufficient):
        return Insufficient("ensemble_weights", "no backtest: " + results.reason, results.detail)
    sc = {m: v[horizon] for m, v in results.get("models", {}).items() if horizon in v and v[horizon].get("n")}
    if not sc:
        return Insufficient("ensemble_weights", f"no model has out-of-sample errors at horizon {horizon}")
    eq = 1.0 / len(sc)
    inv = {m: 1.0 / max(s["rmse"] ** 2, mse_floor) for m, s in sc.items()}
    tot = sum(inv.values())
    n_eff = min(s["n"] for s in sc.values()) / max(1, horizon)
    lam = n_eff / (n_eff + shrink_n)
    w = {m: lam * inv[m] / tot + (1 - lam) * eq for m in sc}
    s = sum(w.values())
    return {m: v / s for m, v in sorted(w.items())}


def ensemble_errors(results: dict, horizon: int, weights: dict[str, float]) -> list[float]:
    """Out-of-sample log errors of the weighted ensemble at ``horizon``: Σ wₘ·eₘ at origins where every weighted model
    has an error (weights renormalised over those models). Empty when there is no common origin."""
    errs = results["errors"]
    ms = [m for m, w in weights.items() if w > 0 and errs.get(m, {}).get(horizon)]
    if not ms:
        return []
    common = set.intersection(*(set(errs[m][horizon]) for m in ms))
    tot = sum(weights[m] for m in ms)
    return [sum(weights[m] / tot * errs[m][horizon][o] for m in ms) for o in sorted(common)]
