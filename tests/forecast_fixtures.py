"""Synthetic monthly price series for the forecast tests (deterministic)."""
import math
import random

from vnrealty.forecast.series import month_add


def walk(n: int, start: str = "2016-01", level: float = 30e6, drift_annual: float = 0.08, vol: float = 0.01,
         seed: int = 1) -> list[tuple[str, float]]:
    """``n`` months of a lognormal random walk with drift (VND/m²)."""
    rng = random.Random(seed)
    mu = math.log(1 + drift_annual) / 12
    out, y = [], math.log(level)
    for k in range(n):
        out.append((month_add(start, k), math.exp(y)))
        y += mu + rng.gauss(0, vol)
    return out


def ar_cycle(n: int, start: str = "2014-01", level: float = 20e6, mu_annual: float = 0.06, rho: float = 0.9,
             vol: float = 0.004, seed: int = 3) -> list[tuple[str, float]]:
    """Monthly growth g_t = μ + ρ(g_{t−1} − μ) + ε: a boom/bust cycle around a long-run growth."""
    rng = random.Random(seed)
    mu = math.log(1 + mu_annual) / 12
    g, y, out = mu * 3, math.log(level), []
    for k in range(n):
        out.append((month_add(start, k), math.exp(y)))
        g = mu + rho * (g - mu) + rng.gauss(0, vol)
        y += g
    return out
