import unittest

from vnrealty.forecast import asset as A
from vnrealty.types import Estimate, Insufficient


def flat_fan(months=72, last="2026-10", spread=0.0):
    """A deterministic fan: area flat at 100 with a constant ± spread (fraction)."""
    from vnrealty.forecast.series import month_add
    return {"last_month": last, "last_value": 100.0, "months": [month_add(last, k + 1) for k in range(months)],
            "p10": [100 * (1 - spread)] * months, "p50": [100.0] * months, "p90": [100 * (1 + spread)] * months}


V = Estimate("triangulated", 5e9, 5e9, 5e9, n=3)


class TestOverlayRule(unittest.TestCase):
    CATS = [{"id": "road", "p": 1.0, "uplift": 0.20, "year": 2028, "local": True, "area_uplift": 0.05},
            {"id": "bridge", "p": 1.0, "uplift": 0.10, "year": 2028},
            {"id": "gate", "p": 1.0, "uplift": 0.1, "year": 2028, "local": True}]

    def test_only_local_net_of_area(self):
        used, skipped = A.overlay_catalysts(self.CATS)
        self.assertEqual([c["id"] for c in used], ["road"])
        self.assertAlmostEqual(used[0]["uplift"], 0.15)
        reasons = {s["id"]: s["reason"] for s in skipped}
        self.assertIn("already reflected", reasons["bridge"])
        self.assertIn("area_uplift missing", reasons["gate"])
        allc, _ = A.overlay_catalysts(self.CATS, include_area_catalysts=True)
        self.assertEqual(len(allc), 3)

    def test_projection_no_double_count(self):
        p = A.project_asset(V, flat_fan(), self.CATS, 4, "2026-11")
        rows = p["rows"]
        self.assertAlmostEqual(rows[0]["p50"], 5e9)
        self.assertAlmostEqual(rows[2]["p50"] / (5e9 * 1.15), 1.0)        # road landed: net 15%, bridge not added
        self.assertAlmostEqual(rows[2]["overlay_expected"], 1.15)
        q = A.project_asset(V, flat_fan(), self.CATS, 4, "2026-11", include_area_catalysts=True)
        self.assertAlmostEqual(q["rows"][2]["p50"] / (5e9 * 1.2 * 1.1 * 1.1), 1.0)
        self.assertIn("double count", q["rule"])
        self.assertEqual(p["horizons"], [12, 24, 36, 48])


class TestProjection(unittest.TestCase):
    def test_bands_and_beyond_fan(self):
        v = Estimate("triangulated", 5e9, 4e9, 6e9)
        p = A.project_asset(v, flat_fan(months=30, spread=0.1), [], 3, "2026-10", seed=3)
        r0, r2, r3 = p["rows"][0], p["rows"][2], p["rows"][3]
        self.assertLess(r0["p10"], 5e9)
        self.assertGreater(r0["p90"], 5e9)
        self.assertIsNone(r3["p50"])
        self.assertIn("beyond", r3["note"])
        self.assertEqual(len(p["p50"]), 2)
        self.assertEqual(p, A.project_asset(v, flat_fan(months=30, spread=0.1), [], 3, "2026-10", seed=3))
        self.assertIsInstance(A.project_asset(Insufficient("x", "no comps"), flat_fan(), [], 3, "2026-11"), Insufficient)
        self.assertIsInstance(A.project_asset(v, flat_fan(), [], 3, "2026-01"), Insufficient)

    def test_conditional_area_spread(self):
        # start one year after the fan's last month: the year already passed is not counted again
        fan = flat_fan(months=60)
        fan["p50"] = [100 * 1.01 ** (k + 1) for k in range(60)]
        p = A.project_asset(V, fan, [], 2, "2027-10")
        self.assertAlmostEqual(p["rows"][0]["p50"], 5e9)
        self.assertAlmostEqual(p["rows"][1]["area_mult_p50"], 1.01 ** 12, places=9)

    def test_sell_timing(self):
        fan = flat_fan()
        fan["p50"] = fan["p10"] = fan["p90"] = [100 * 1.01 ** (k + 1) for k in range(72)]   # ~12.7%/yr
        p = A.project_asset(V, fan, [], 4, "2026-10")
        st = A.sell_timing(p, sell_cost=0.02, deposit_rate=0.05)
        self.assertEqual(st["best"], 4)
        self.assertGreater(st["best_edge"], 0)
        st2 = A.sell_timing(p, sell_cost=0.02, deposit_rate=0.20)
        self.assertEqual(st2["best"], 0)
        self.assertIn("edge_p10", st["rows"][1])


if __name__ == "__main__":
    unittest.main()
