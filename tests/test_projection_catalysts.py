import math
import unittest

from vnrealty.projection.catalysts import effective_uplift, hold_vs_sell, market_path, paths

MKT = {"y1": -0.04, "later": 0.03}
CATS = [{"id": "a", "p": 0.6, "uplift": 0.10, "year": 2029}, {"id": "b", "p": 0.9, "uplift": 0.03, "year": 2027}]


class TestPaths(unittest.TestCase):
    def test_market_path(self):
        m = market_path(MKT, 3)
        self.assertAlmostEqual(m[3], 0.96 * 1.03 * 1.03)

    def test_bear_base_bull_order(self):
        p = paths(MKT, CATS, 5, 2026)
        self.assertEqual(p["years"][0], 2026)
        self.assertEqual(p["bear"], market_path(MKT, 5))
        for t in range(1, 6):
            self.assertLessEqual(p["bear"][t], p["base"][t])
            self.assertLessEqual(p["base"][t], p["bull"][t])
        self.assertAlmostEqual(p["bull"][5] / p["bear"][5], 1.10 * 1.03)
        self.assertAlmostEqual(p["contrib"]["a"], p["bear"][5] * 0.10 * 0.6)

    def test_ramp_is_linear(self):
        p = paths({"y1": 0, "later": 0}, [{"id": "x", "p": 1, "uplift": 0.3, "year": 2029}], 3, 2026)
        self.assertAlmostEqual(p["base"][1], 1.1)
        self.assertAlmostEqual(p["base"][3], 1.3)

    def test_distance_decay(self):
        c = {"id": "x", "p": 1, "uplift": 0.2, "year": 2028, "distance_km": 2.0, "decay_km": 2.0}
        self.assertAlmostEqual(effective_uplift(c), 0.2 * math.exp(-1))
        self.assertEqual(effective_uplift({"uplift": 0.2}), 0.2)

    def test_bad_probability(self):
        with self.assertRaises(ValueError):
            paths(MKT, [{"id": "x", "p": 60, "uplift": 0.1, "year": 2028}], 3, 2026)


class TestHoldVsSell(unittest.TestCase):
    def test_flat_path_sell_now(self):
        r = hold_vs_sell(1e9, 1.0, 0.03, 0.05, [1.0] * 4)
        self.assertEqual(r["best"], 0)
        self.assertAlmostEqual(r["sell_now"], 0.97e9)

    def test_fast_growth_hold(self):
        r = hold_vs_sell(1e9, 0.5, 0.03, 0.05, [1.0, 1.2, 1.4, 1.5], start_year=2026)
        self.assertEqual(r["best"], 3)
        self.assertEqual(r["rows"][3]["year"], 2029)
        self.assertAlmostEqual(r["rows"][1]["take_home"], 1e9 * 1.2 * 0.5 * 0.97)
        self.assertAlmostEqual(r["rows"][2]["deposit"], 0.5 * 0.97e9 * 1.05 ** 2)

    def test_holding_cost(self):
        r = hold_vs_sell(1e9, 1.0, 0.0, 0.0, [1.0, 1.0], holding_cost=1e7)
        self.assertAlmostEqual(r["rows"][1]["edge"], -1e7)


if __name__ == "__main__":
    unittest.main()
