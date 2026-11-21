"""compare(): normalised rows from engine outputs and ranks per metric."""
import unittest
from dataclasses import replace

from vnrealty.deal.engine import Deal, analyse
from vnrealty.plan.compare import compare

D = Deal()


class Compare(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"name": "a", "deal": D, "est_value": 3.3e9, "area_m2": 100},
            {"name": "b", "deal": replace(D, price=2.5e9, value_after=2.6e9, rent=22e6), "extra": {"area_m2": 80}},
            {"name": "c", "deal": replace(D, loan=0.0)},
        ]
        self.r = compare(self.items)

    def test_rows_are_engine_numbers(self):
        a = analyse(D)
        row = self.r["rows"][0]
        self.assertAlmostEqual(row["irr"], a["irr"])
        self.assertAlmostEqual(row["equity"], a["cash_in"])
        self.assertAlmostEqual(row["price_m2"], D.price / 100)
        self.assertAlmostEqual(row["value_gap"], 0.1)
        self.assertAlmostEqual(self.r["rows"][1]["price_m2"], 2.5e9 / 80)

    def test_missing_inputs_are_none_and_unranked(self):
        c = self.r["rows"][2]
        self.assertIsNone(c["price_m2"])
        self.assertIsNone(c["dscr"])
        self.assertIsNone(c["rank"]["value_gap"])
        self.assertEqual(self.r["ranks"]["value_gap"], ["a"])

    def test_rank_direction(self):
        self.assertEqual(self.r["ranks"]["price"][0], "b")
        self.assertEqual(self.r["ranks"]["equity"][-1], "c")      # all-cash needs the most equity
        irr = sorted(self.r["rows"], key=lambda x: -x["irr"])
        self.assertEqual(self.r["ranks"]["irr"], [x["name"] for x in irr])

    def test_ties_share_rank_and_names_unique(self):
        r = compare([{"name": "x", "deal": D}, {"name": "y", "deal": D}])
        self.assertEqual(r["rows"][0]["rank"]["irr"], r["rows"][1]["rank"]["irr"])
        with self.assertRaises(ValueError):
            compare([{"name": "x", "deal": D}, {"name": "x", "deal": D}])


if __name__ == "__main__":
    unittest.main()
