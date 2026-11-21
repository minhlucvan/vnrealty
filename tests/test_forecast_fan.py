import unittest

from tests.forecast_fixtures import walk
from vnrealty.forecast.fan import fan
from vnrealty.forecast.models import default_models
from vnrealty.types import Insufficient


class TestFan(unittest.TestCase):
    def test_fan_widens_and_is_deterministic(self):
        s = walk(96, vol=0.012)
        f = fan(s, default_models(), None, 24, n=500)
        self.assertEqual(len(f["p50"]), 24)
        self.assertEqual(f["months"][0], "2024-01")
        for a, b, c in zip(f["p10"], f["p50"], f["p90"]):
            self.assertLess(a, b)
            self.assertLess(b, c)
        w = [hi / lo for lo, hi in zip(f["p10"], f["p90"])]
        self.assertTrue(all(w2 >= w1 - 1e-12 for w1, w2 in zip(w, w[1:])))
        self.assertGreater(w[-1], w[0])
        self.assertAlmostEqual(f["mult50"][0], f["p50"][0] / s[-1][1])
        self.assertEqual(f, fan(s, default_models(), None, 24, n=500))
        self.assertNotEqual(f["p10"], fan(s, default_models(), None, 24, n=500, seed=8)["p10"])

    def test_fixed_weights_and_insufficient(self):
        s = walk(60)
        f = fan(s, default_models(), {"rw_drift": 1.0}, 6, n=300)
        self.assertEqual(f["weights"][6], {"rw_drift": 1.0})
        r = fan(walk(20), default_models(), None, 12)
        self.assertIsInstance(r, Insufficient)
        self.assertIn("months_needed", r.detail)


if __name__ == "__main__":
    unittest.main()
