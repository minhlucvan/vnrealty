import unittest

from vnrealty.stats import bootstrap_ci, iqr, median, ols, quantile, weighted_median


class TestStats(unittest.TestCase):
    def test_quantiles(self):
        self.assertEqual(median([3, 1, 2]), 2)
        self.assertEqual(median([1, 2, 3, 4]), 2.5)
        self.assertIsNone(quantile([], 0.5))
        self.assertEqual(iqr([1, 2, 3, 4, 5]), (2, 4))

    def test_weighted_median(self):
        self.assertEqual(weighted_median([1, 2, 3], [1, 1, 10]), 3)

    def test_ols_recovers_line(self):
        X = [[1, x] for x in range(10)]
        y = [2 + 3 * x for x in range(10)]
        r = ols(X, y, ["c", "x"])
        self.assertAlmostEqual(r.coef()["c"], 2, places=9)
        self.assertAlmostEqual(r.coef()["x"], 3, places=9)
        self.assertAlmostEqual(r.r2, 1.0, places=9)

    def test_ols_singular_is_none(self):
        self.assertIsNone(ols([[1, 1], [1, 1], [1, 1]], [1, 2, 3]))

    def test_bootstrap_deterministic(self):
        xs = list(range(20))
        self.assertEqual(bootstrap_ci(xs, median), bootstrap_ci(xs, median))


if __name__ == "__main__":
    unittest.main()
