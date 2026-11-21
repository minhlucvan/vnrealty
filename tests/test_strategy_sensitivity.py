"""Sensitivity: tornado ordering and break-even by bisection."""
import unittest
from dataclasses import replace

from vnrealty.deal.engine import Deal, analyse
from vnrealty.strategy import catalog as C
from vnrealty.strategy.sensitivity import break_even, tornado
from vnrealty.types import Insufficient
from tests.strategy_fixtures import FULL, M, OPP

D = Deal(price=3e9, renovation=100 * M, value_after=3.1e9, loan=1.5e9, rent=20 * M, hold_years=10, hurdle=0.10)


class Tornado(unittest.TestCase):
    def test_deal_sorted_by_swing(self):
        t = tornado(D, None, {"buy_costs": (0.01, 0.02), "rent": (15 * M, 25 * M), "float_rate": (0.08, 0.13)})
        self.assertEqual(t["rows"][-1]["input"], "buy_costs")
        swings = [r["swing"] for r in t["rows"]]
        self.assertEqual(swings, sorted(swings, reverse=True))
        r = next(r for r in t["rows"] if r["input"] == "rent")
        self.assertAlmostEqual(r["npv_low"], analyse(replace(D, rent=15 * M))["npv"], delta=1)
        self.assertAlmostEqual(t["base"]["npv"], analyse(D)["npv"], delta=1)

    def test_strategy_function(self):
        fn = lambda a: C.build("fix_flip", OPP, a)
        t = tornado(fn, FULL, {"after_repair_value": (3.5e9, 4.2e9), "flip_renovation": (250 * M, 350 * M)})
        self.assertEqual(t["rows"][0]["input"], "after_repair_value")
        self.assertLess(t["rows"][0]["npv_low"], t["rows"][0]["npv_high"])

    def test_insufficient(self):
        fn = lambda a: C.build("subdivide", OPP, a)
        t = tornado(fn, FULL, {"lots": (2, 9)})
        self.assertIn("insufficient", t["rows"][0])
        self.assertIsInstance(tornado(fn, {}, {"lots": (2, 3)}), Insufficient)


class BreakEven(unittest.TestCase):
    def test_rent_for_hurdle(self):
        b = break_even(D, "rent")
        self.assertAlmostEqual(analyse(replace(D, rent=b["break_even"]))["irr"], 0.10, places=5)
        self.assertEqual(b["direction"], "higher_is_better")
        self.assertAlmostEqual(b["margin"], b["break_even"] / (20 * M) - 1)

    def test_rate_lower_is_better(self):
        b = break_even(D, "float_rate", target="npv", hi=0.5)
        if isinstance(b, Insufficient):
            self.skipTest(b.reason)
        self.assertEqual(b["direction"], "lower_is_better")
        self.assertAlmostEqual(analyse(replace(D, float_rate=b["break_even"]))["npv"], 0, delta=1e4)

    def test_no_crossing_and_int_field(self):
        self.assertIsInstance(break_even(D, "rent", lo=100 * M, hi=200 * M), Insufficient)
        with self.assertRaises(ValueError):
            break_even(D, "hold_years")
        with self.assertRaises(ValueError):
            break_even(D, "rent", target="moic")

    def test_strategy_function_arv(self):
        fn = lambda a: C.build("fix_flip", OPP, a)
        b = break_even(fn, "after_repair_value", target="npv", base_assumptions=FULL)
        m = C.metrics(fn({**FULL, "after_repair_value": b["break_even"]}))
        self.assertAlmostEqual(m["npv"], 0, delta=1e3)
        self.assertLess(b["break_even"], FULL["after_repair_value"])
        self.assertIsInstance(break_even(fn, "nope", base_assumptions=FULL), Insufficient)


if __name__ == "__main__":
    unittest.main()
