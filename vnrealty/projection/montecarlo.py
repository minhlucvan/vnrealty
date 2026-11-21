"""Monte Carlo price paths: lognormal market noise plus catalysts that land (or not) with random delays.

Per simulated path and year: the market multiplies by exp(N(ln(1 + drift) − vol²/2, vol)), so the *median* annual
growth is (1 + drift)·exp(−vol²/2) and the mean is 1 + drift. Each catalyst lands with probability ``p``; when it does,
its completion year is ``year`` + N(0, ``delay_sd_years``) (never before ``start_year`` + 1) and its uplift (after
distance decay, see :func:`catalysts.effective_uplift`) ramps in linearly until then.

Deterministic for a given ``seed``. Money VND; rates fractions.
"""
from __future__ import annotations

import math
import random

from vnrealty.projection.catalysts import effective_uplift
from vnrealty.stats import quantile

__all__ = ["simulate"]


def simulate(price0: float, years: int, drift: float, vol: float, catalysts: list[dict] | None = None, n: int = 2000,
             seed: int = 7, delay_sd_years: float = 1.0, start_year: int | None = None,
             hurdle_rate: float | None = None) -> dict:
    """Simulate ``n`` paths of ``years`` years from ``price0`` (VND).

    Returns ``years`` (offsets 0..Y or calendar years when ``start_year`` is given), ``p10``/``p50``/``p90`` per year
    (VND), ``mean``, and — when ``hurdle_rate`` is given — ``p_beat_hurdle`` per year: P(price_t > price0·(1+h)^t).
    ``start_year`` is required when any catalyst is given (catalyst years are calendar years).
    """
    cats = catalysts or []
    if cats and start_year is None:
        raise ValueError("start_year is required when catalysts are given")
    for c in cats:
        if not 0 <= float(c["p"]) <= 1:
            raise ValueError(f"catalyst {c.get('id')}: p must be in [0, 1]")
    rng = random.Random(seed)
    mu = math.log(1 + drift) - vol * vol / 2
    sims = [[0.0] * (years + 1) for _ in range(n)]
    for i in range(n):
        lands = []
        for c in cats:
            if rng.random() < float(c["p"]):
                done = max(start_year + 1, float(c["year"]) + rng.gauss(0, delay_sd_years))
                lands.append((effective_uplift(c), done - start_year))
        level = price0
        sims[i][0] = price0
        for t in range(1, years + 1):
            level *= math.exp(rng.gauss(mu, vol))
            lift = math.prod(1 + u * min(1.0, t / max(1e-9, span)) for u, span in lands)
            sims[i][t] = level * lift
    cols = [[s[t] for s in sims] for t in range(years + 1)]
    out = {"years": [(start_year or 0) + t for t in range(years + 1)],
           "p10": [quantile(c, 0.10) for c in cols], "p50": [quantile(c, 0.50) for c in cols],
           "p90": [quantile(c, 0.90) for c in cols], "mean": [sum(c) / n for c in cols], "n": n, "seed": seed}
    if hurdle_rate is not None:
        out["p_beat_hurdle"] = [sum(v > price0 * (1 + hurdle_rate) ** t for v in c) / n for t, c in enumerate(cols)]
    return out
