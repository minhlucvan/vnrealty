import unittest

from tests.forecast_fixtures import ar_cycle, walk
from vnrealty.forecast import backtest as B
from vnrealty.forecast.models import default_models
from vnrealty.types import Insufficient


class TestBacktest(unittest.TestCase):
    def test_too_short_is_insufficient(self):
        r = B.walk_forward(walk(20), default_models())
        self.assertIsInstance(r, Insufficient)
        self.assertEqual(r.detail["months_needed"], 7)

    def test_walk_forward_scores(self):
        s = walk(84, vol=0.01)
        r = B.walk_forward(s, default_models(), horizons=(3, 12))
        rw = r["models"]["rw_drift"]
        self.assertEqual(rw[3]["n"], 84 - 24 - 3 + 1)
        self.assertEqual(rw[12]["n"], 84 - 24 - 12 + 1)
        self.assertGreater(rw[12]["rmse"], rw[3]["rmse"])           # error grows with horizon
        self.assertTrue(0 <= rw[3]["coverage"] <= 1)
        self.assertIn("ar_growth", r["models"])
        self.assertEqual(r["best"].keys(), {3, 12})
        self.assertEqual(r, B.walk_forward(s, default_models(), horizons=(3, 12)))    # deterministic
        r24 = B.walk_forward(walk(40), default_models(), horizons=(3, 24))
        self.assertEqual(r24["horizons_unscored"], {24: 8})
        self.assertEqual(r24["models"]["rw_drift"][24], {"n": 0})

    def test_pit_no_lookahead(self):
        s = walk(70)
        a = B.walk_forward(s, default_models(), horizons=(3,), as_of="2020-06")
        b = B.walk_forward(s[:54], default_models(), horizons=(3,))
        self.assertEqual(a["models"], b["models"])

    def test_weights(self):
        r = B.walk_forward(ar_cycle(110), default_models(), horizons=(6,))
        w = B.ensemble_weights(r, 6)
        self.assertAlmostEqual(sum(w.values()), 1.0)
        best = r["best"][6]
        self.assertEqual(max(w, key=w.get), best)
        thin = B.ensemble_weights(r, 6, shrink_n=1e9)
        for v in thin.values():
            self.assertAlmostEqual(v, 1 / len(thin), places=6)
        self.assertIsInstance(B.ensemble_weights(r, 99), Insufficient)
        e = B.ensemble_errors(r, 6, w)
        self.assertGreater(len(e), 10)


if __name__ == "__main__":
    unittest.main()
