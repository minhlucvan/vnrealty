import math
import unittest

from vnrealty.projection.montecarlo import simulate


class TestMonteCarlo(unittest.TestCase):
    def test_deterministic_per_seed(self):
        a = simulate(1e9, 5, 0.03, 0.1, n=300, seed=3)
        b = simulate(1e9, 5, 0.03, 0.1, n=300, seed=3)
        c = simulate(1e9, 5, 0.03, 0.1, n=300, seed=4)
        self.assertEqual(a, b)
        self.assertNotEqual(a["p50"], c["p50"])

    def test_quantiles_ordered_and_drift(self):
        r = simulate(1e9, 5, 0.04, 0.12, n=4000)
        self.assertEqual(r["p50"][0], 1e9)
        for t in range(1, 6):
            self.assertLess(r["p10"][t], r["p50"][t])
            self.assertLess(r["p50"][t], r["p90"][t])
        self.assertAlmostEqual(r["mean"][5] / 1e9, 1.04 ** 5, delta=0.04)

    def test_zero_vol_with_certain_catalyst(self):
        cat = [{"id": "x", "p": 1.0, "uplift": 0.2, "year": 2028}]
        r = simulate(1e9, 3, 0.0, 0.0, cat, n=50, delay_sd_years=0, start_year=2026)
        self.assertAlmostEqual(r["p50"][1], 1.1e9)
        self.assertAlmostEqual(r["p50"][3], 1.2e9)
        self.assertEqual(r["years"], [2026, 2027, 2028, 2029])

    def test_hurdle(self):
        r = simulate(1e9, 3, 0.10, 0.0, n=20, hurdle_rate=0.05)
        self.assertEqual(r["p_beat_hurdle"][1:], [1.0, 1.0, 1.0])
        r2 = simulate(1e9, 3, 0.0, 0.0, n=20, hurdle_rate=0.05)
        self.assertEqual(r2["p_beat_hurdle"][3], 0.0)

    def test_start_year_required_with_catalysts(self):
        with self.assertRaises(ValueError):
            simulate(1e9, 3, 0.0, 0.1, [{"id": "x", "p": 0.5, "uplift": 0.1, "year": 2028}])


if __name__ == "__main__":
    unittest.main()
