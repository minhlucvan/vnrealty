import unittest

from vnrealty.pricing import score as S


def peer(pct, z=0.0, n=20):
    return {"scope": "ward", "n": n, "median": 50e6, "percentile": pct, "z": z}


class TestPoints(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(S.points("price_m2", {"value": 1, "unit": "x", "peer": peer(20)}), 80)
        self.assertEqual(S.points("residual_vs_asking", {"value": 1.2, "ratio": 1.2}), 70)
        self.assertEqual(S.points("residual_vs_asking", {"value": 3, "ratio": 3}), 100)
        self.assertEqual(S.points("price_to_rent", {"value": 20, "ratio": 0.8}), 70)
        self.assertEqual(S.points("hedonic_residual", {"value": -0.2}), 70)
        self.assertIsNone(S.points("price_m2", {"insufficient": "x"}))
        self.assertIsNone(S.points("price_m2", {"value": 1, "peer": {"insufficient": "thin"}}))
        self.assertIsNone(S.points("net_yield", {"value": 0.05, "ratio": 1.0, "independent": False}))
        self.assertIsNone(S.points("days_on_market", {"value": 10}))  # not scored


class TestScore(unittest.TestCase):
    def test_weighted_score_and_confidence(self):
        m = {"price_m2": {"value": 4e7, "unit": "VND/m²", "peer": peer(10)},          # 90 pts, w .25
             "price_per_buildable_m2": {"value": 1e7, "unit": "VND/m²", "peer": peer(30)},  # 70, w .20
             "residual_vs_asking": {"value": 1.1, "unit": "×", "ratio": 1.1}}       # 60, w .30
        r = S.pricing_score(m, "land")
        self.assertAlmostEqual(r["score"], (0.25 * 90 + 0.20 * 70 + 0.30 * 60) / 0.75)
        self.assertAlmostEqual(r["confidence"], 0.75)
        self.assertEqual(r["why"]["strongest"][0]["metric"], "price_m2")
        self.assertEqual(r["why"]["weakest"][0]["metric"], "residual_vs_asking")
        self.assertEqual({x["metric"] for x in r["missing"]}, {"price_per_frontage_m", "hedonic_residual", "value_gap"})

    def test_withheld_below_half_confidence(self):
        r = S.pricing_score({"price_m2": {"value": 1, "peer": peer(10)}}, "land")
        self.assertIsNone(r["score"])
        self.assertIn("confidence", r["withheld_reason"])

    def test_custom_weights(self):
        r = S.pricing_score({"price_m2": {"value": 1, "peer": peer(40)}}, "land", weights={"price_m2": 1.0})
        self.assertEqual((r["score"], r["confidence"]), (60, 1.0))

    def test_red_flags(self):
        m = {"price_m2": {"value": 1, "peer": peer(1, z=-4.0)}, "legal_status": {"value": "giay_tay"},
             "alley_m": {"value": 1.5}, "negotiable": {"value": True}, "days_on_market": {"value": 400},
             "official_ratio": {"value": 0.8}}
        flags = " | ".join(S.red_flags(m, "land"))
        for s in ("giấy tay", "kiệt 1.5", "thỏa thuận", "stale", "official", "too cheap: verify"):
            self.assertIn(s, flags)
        self.assertEqual(S.red_flags({"alley_m": {"value": 0.0}, "legal_status": {"value": "so_hong"}}, "land"), [])


if __name__ == "__main__":
    unittest.main()
