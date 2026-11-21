import math
import random
import unittest

from tests.valuation_fixtures import close_all, add_listing, db
from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation.hedonic import alley_bucket, fit, legal_bucket, predict, residual

WARD = {"w-a": 0.0, "w-b": 0.3, "w-c": -0.2}
ALLEY = {0.0: 0.5, 5.0: 0.0, 3.5: -0.15, 2.0: -0.3}


def build(n=120, noise=0.02, seed=1):
    con, rng = db(), random.Random(seed)
    for i in range(n):
        ward = rng.choice(list(WARD))
        alley = rng.choice(list(ALLEY))
        corner = rng.random() < 0.3
        area = rng.uniform(60, 200)
        month = rng.choice(["2026-08", "2026-09", "2026-10"])
        legal = "giay_tay" if rng.random() < 0.15 else "so_hong"
        lp = math.log(50e6) + WARD[ward] + ALLEY[alley] + 0.08 * corner - 0.1 * math.log(area / 100) \
            + (0.02 if month == "2026-10" else 0) - (0.25 if legal == "giay_tay" else 0) + rng.gauss(0, noise)
        add_listing(con, ward=ward, alley=alley, corner=int(corner), area=area, legal=legal,
                    obs=[(f"{month}-15", math.exp(lp) * area, "asking")])
    return con


class TestHedonic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = build()
        cls.model = fit(cls.con, "2026-11-01")

    def test_buckets(self):
        self.assertEqual(alley_bucket(0), "street")
        self.assertEqual(alley_bucket(5), "wide")
        self.assertEqual(alley_bucket(3.5), "mid")
        self.assertEqual(alley_bucket(2), "narrow")
        self.assertEqual(alley_bucket(None), "unknown")
        self.assertEqual(legal_bucket("so_do"), "cert")

    def test_recovers_coefficients(self):
        c = self.model.ols.coef()
        self.assertAlmostEqual(c["corner"], 0.08, delta=0.02)
        self.assertAlmostEqual(c["log_area"], -0.1, delta=0.03)
        self.assertAlmostEqual(c["ward=w-b"], 0.3, delta=0.02)
        self.assertAlmostEqual(c["legal=giay_tay"], -0.25, delta=0.03)
        self.assertLess(self.model.sigma, 0.04)

    def test_predict_band_and_haircut(self):
        s = {"ptype": "land", "ward_code": "w-b", "area_m2": 100, "alley_m": 5.0, "corner": False, "legal": "so_hong"}
        raw = predict(self.model, s, haircut=False)
        cut = predict(self.model, s)
        self.assertIsInstance(raw, Estimate)
        expect = math.exp(math.log(50e6) + 0.3 + 0.02) * 100
        self.assertAlmostEqual(raw.value / expect, 1, delta=0.03)
        self.assertLess(raw.lo, raw.value)
        self.assertGreater(raw.hi, raw.value)
        self.assertAlmostEqual(cut.value / raw.value, cut.detail["haircut"]["value"])

    def test_unseen_ward_is_insufficient(self):
        s = {"ptype": "land", "ward_code": "w-zzz", "area_m2": 100}
        self.assertIsInstance(predict(self.model, s), Insufficient)

    def test_residual_screen(self):
        cheap = {"ptype": "land", "ward_code": "w-a", "area_m2": 100, "alley_m": 5.0, "corner": False,
                 "legal": "so_hong", "price": 0.7 * 50e6 * 100, "seen_at": "2026-09-10"}
        r = residual(self.model, cheap)
        self.assertAlmostEqual(r, math.log(0.7), delta=0.03)

    def test_thin_data_insufficient(self):
        self.assertIsInstance(fit(build(n=10), "2026-11-01"), Insufficient)

    def test_point_in_time(self):
        self.assertIsInstance(fit(self.con, "2026-07-01"), Insufficient)


def tearDownModule():
    close_all()


if __name__ == "__main__":
    unittest.main()
