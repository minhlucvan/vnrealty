import math
import unittest

from tests.forecast_fixtures import ar_cycle, walk
from vnrealty.forecast import models as M
from vnrealty.forecast.series import month_add
from vnrealty.types import Insufficient


class TestModels(unittest.TestCase):
    def test_rw_drift_recovers_drift_and_shrinks(self):
        s = walk(120, drift_annual=0.10, vol=0.002)
        f = M.fit_rw_drift(s)
        self.assertAlmostEqual(f.params["drift_annual"], 0.10, delta=0.01)
        path = f.forecast(12)
        self.assertEqual(path[0][0], month_add(s[-1][0], 1))
        self.assertAlmostEqual(path[-1][1] / s[-1][1], 1 + f.params["drift_annual"], places=6)
        g = M.fit_rw_drift(s, prior_annual=0.0)
        self.assertLess(g.params["drift_annual"], f.params["drift_annual"])
        self.assertGreater(g.params["drift_annual"], 0.0)

    def test_pit_as_of(self):
        s = walk(60)
        f = M.fit_rw_drift(s, as_of="2018-12-15")
        self.assertEqual(f.last_month, "2018-12")
        self.assertEqual(f.n, 36)
        self.assertEqual(M.fit_rw_drift(s, as_of="2018-12").forecast(3), f.forecast(3))   # deterministic

    def test_insufficient_says_months_needed(self):
        r = M.fit_ar_growth(walk(20))
        self.assertIsInstance(r, Insufficient)
        self.assertEqual(r.detail["months_needed"], 10)
        self.assertIsInstance(M.fit_local_trend(walk(5)), Insufficient)

    def test_local_trend_follows_trend(self):
        s = [(month_add("2020-01", k), 100 * math.exp(0.01 * k)) for k in range(40)]
        f = M.fit_local_trend(s)
        self.assertGreater(f.forecast(6)[-1][1], s[-1][1])
        self.assertIn(f.params["phi"], (0.8, 0.9, 0.98))

    def test_ar_growth_reverts(self):
        s = ar_cycle(150)
        f = M.fit_ar_growth(s, prior_annual=0.0)
        self.assertGreaterEqual(f.params["rho"], 0.0)
        self.assertLessEqual(f.params["rho"], 0.99)
        lv = f.forecast_log(240)
        late = (lv[-1] - lv[-13])                    # 12-month growth far out ≈ μ = 0
        self.assertLess(abs(late), abs(f.params["g12_last"]) + 1e-9)

    def test_driver_regression(self):
        s = walk(60, vol=0.0005, seed=4)
        # growth driven by a driver lagged 3 months
        import random
        rng = random.Random(2)
        drv = {month_add("2015-10", k): rng.uniform(-1, 1) for k in range(80)}
        y, pts = math.log(30e6), []
        for k in range(60):
            m = month_add("2016-01", k)
            pts.append((m, math.exp(y)))
            y += 0.005 + 0.01 * drv[month_add(m, -2)]      # next month's growth uses x(t+1−3)
        r = M.fit_driver_regression(pts, drivers={"credit": sorted(drv.items())})
        self.assertAlmostEqual(r.params["coef"]["credit"], 0.01, delta=1e-6)
        self.assertEqual(len(r.forecast(24)), 24)
        self.assertIsInstance(M.fit_driver_regression(pts, drivers={"credit": sorted(drv.items())[:10]}), Insufficient)
        self.assertIsInstance(M.fit_driver_regression(pts), Insufficient)
        self.assertEqual([n for n, _ in M.default_models(drivers={"x": []})][-1], "driver_regression")
        self.assertIsInstance(s, list)


if __name__ == "__main__":
    unittest.main()
