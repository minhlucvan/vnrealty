"""Graded verdict: sub-score formulas, weights, core-missing withholds, bands, legal cap."""
import unittest

from vnrealty.score import WEIGHTS, grade, letter

FULL = {"value_gap": {"estimate": 3.3e9, "ask": 3e9}, "irr": {"irr": 0.12, "hurdle": 0.10},
        "yield": {"yield": 0.06, "ward_median": 0.05}, "ev": {"p_loss": 0.1},
        "risk": {"flags": [{"severity": "medium"}]}, "legal": {"status": "clear"}, "liquidity": {"days_to_sell": 90}}


class Grade(unittest.TestCase):
    def test_bands(self):
        self.assertEqual([letter(x) for x in (85, 84.9, 70, 55, 40, 25, 24.9)], ["A+", "A", "A", "B", "C", "D", "F"])

    def test_subscores_follow_documented_formulas(self):
        g = grade(FULL)
        s = g["subscores"]
        self.assertAlmostEqual(s["value_gap"]["score"], 75)
        self.assertAlmostEqual(s["irr"]["score"], 60)
        self.assertAlmostEqual(s["yield"]["score"], 70)
        self.assertAlmostEqual(s["ev"]["score"], 80)
        self.assertAlmostEqual(s["risk"]["score"], 85)
        self.assertAlmostEqual(s["liquidity"]["score"], 100 * 275 / 335)
        exp = sum(WEIGHTS[k] * s[k]["score"] for k in WEIGHTS)
        self.assertAlmostEqual(g["score"], exp)
        self.assertEqual(g["letter"], letter(exp))
        self.assertIn("IRR 12.0% vs hurdle 10.0%", g["verdict"])

    def test_missing_core_withholds(self):
        g = grade({k: v for k, v in FULL.items() if k != "irr"})
        self.assertEqual(g["status"], "incomplete")
        self.assertIsNone(g["score"])
        g2 = grade(dict(FULL, irr={"irr": None, "hurdle": 0.1}))
        self.assertEqual(g2["status"], "incomplete")

    def test_missing_optional_renormalises(self):
        g = grade({"value_gap": FULL["value_gap"], "irr": FULL["irr"]})
        self.assertAlmostEqual(g["score"], (75 + 60) / 2)
        self.assertIn("liquidity", g["missing"])

    def test_band_shrinks_value_gap(self):
        tight = grade({"value_gap": {"estimate": 3.3e9, "ask": 3e9, "lo": 3.1e9, "hi": 3.5e9}, "irr": FULL["irr"]})
        wide = grade({"value_gap": {"estimate": 3.3e9, "ask": 3e9, "lo": 2.3e9, "hi": 4.3e9}, "irr": FULL["irr"]})
        self.assertAlmostEqual(tight["subscores"]["value_gap"]["score"], 75)
        self.assertLess(wide["subscores"]["value_gap"]["score"], 75)
        self.assertEqual(tight["subscores"]["value_gap"]["ask_vs_band"], "below")

    def test_legal_issue_caps(self):
        great = dict(FULL, value_gap={"estimate": 4e9, "ask": 3e9}, irr={"irr": 0.3, "hurdle": 0.1})
        self.assertGreater(grade(great)["score"], 39)
        g = grade(dict(great, legal={"status": "issue"}))
        self.assertEqual(g["score"], 39)
        self.assertEqual(g["letter"], "D")
        self.assertTrue(g["legal_capped"])

    def test_custom_weights_and_unknown(self):
        g = grade(FULL, weights={"value_gap": 1, "irr": 1})
        self.assertAlmostEqual(g["score"], 67.5)
        with self.assertRaises(ValueError):
            grade(dict(FULL, vibes={"x": 1}))


if __name__ == "__main__":
    unittest.main()
