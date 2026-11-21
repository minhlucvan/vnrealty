import unittest

from tests.valuation_fixtures import close_all, add_listing, add_sale, db
from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation.calibrate import record
from vnrealty.valuation.triangulate import combine, method_weights


class TestCombine(unittest.TestCase):
    def test_equal_weights_span_bands(self):
        a = Estimate("comps", 100, 90, 110, n=6, as_of="2026-11-01")
        b = Estimate("index_moved", 120, 100, 150, n=20, as_of="2026-11-01")
        c = Insufficient("hedonic", "thin")
        e = combine([a, b, c])
        self.assertEqual(e.value, 110)
        self.assertEqual((e.lo, e.hi), (90, 150))
        self.assertEqual(e.detail["insufficient"], [{"method": "hedonic", "reason": "thin"}])

    def test_weights(self):
        a, b = Estimate("comps", 100, 90, 110), Estimate("hedonic", 200, 150, 250)
        self.assertAlmostEqual(combine([a, b], {"comps": 3, "hedonic": 1}).value, 125)
        e = combine([a, b], {"comps": 1})
        self.assertEqual(e.detail["weights_filled_with_mean"], ["hedonic"])

    def test_nothing_usable(self):
        self.assertIsInstance(combine([Insufficient("comps", "x")]), Insufficient)
        self.assertIsInstance(combine([Estimate("comps", 1, 1, 1)], {"comps": 0}), Insufficient)


class TestMethodWeights(unittest.TestCase):
    def test_equal_without_record(self):
        con = db()
        self.assertEqual(method_weights(con, "2026-11-01", ["comps", "hedonic"]), {"comps": 0.5, "hedonic": 0.5})

    def test_better_method_earns_more_and_shrinks(self):
        con = db()
        for i in range(30):
            lid = add_listing(con, obs=[("2026-01-01", 1e9, "asking")])
            add_sale(con, listing_id=lid, sold_at="2026-06-01", price=1e9)
            record(con, f"listing:{lid}", Estimate("comps", 1.02e9, 0.9e9, 1.1e9, as_of="2026-02-01"))
            record(con, f"listing:{lid}", Estimate("hedonic", 1.30e9, 1.0e9, 1.5e9, as_of="2026-02-01"))
        w = method_weights(con, "2026-11-01")
        self.assertGreater(w["comps"], w["hedonic"])
        self.assertAlmostEqual(sum(w.values()), 1.0)
        w_shrunk = method_weights(con, "2026-11-01", shrink_n=1e6)
        self.assertAlmostEqual(w_shrunk["comps"], 0.5, places=3)


def tearDownModule():
    close_all()


if __name__ == "__main__":
    unittest.main()
