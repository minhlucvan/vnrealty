"""Lot options: layout, each option's Deal, Insufficient on missing inputs, break-even, ranking. Synthetic lot."""
import unittest
from dataclasses import replace

from vnrealty.deal.engine import analyse
from vnrealty.plan.options import Lot, OPTION_NAMES, break_even_rent, evaluate, jv_owner, layout, options
from vnrealty.types import Insufficient

M = 1e6
LOT = Lot(value=3e9, area_m2=100, buildable_ratio=0.9, max_floors=4, build_cost_m2=6.5 * M, unit_size_m2=28,
          unit_rent=4.5 * M, shop_rent=10 * M, land_lease_rent=3 * M, homestay_adr=600e3, homestay_occ=0.55,
          homestay_staff=12 * M, chdv_unit_rate=6 * M, chdv_occ=0.85, chdv_staff=8 * M, fit_out_per_unit=35 * M,
          running_cost_per_unit=0.7 * M, deposit_rate=0.055, mortgage_rate=0.10, build_ltv=0.5, hurdle=0.10,
          price_growth=0.05, rent_growth=0.04, rental_yield_gross=0.05, rental_price_growth=0.04,
          rental_running_rate=0.01)


class Layout(unittest.TestCase):
    def test_units_and_cost(self):
        lay = layout(LOT, 4)
        self.assertAlmostEqual(lay["gfa_m2"], 360)
        self.assertEqual(lay["units"], int(360 * 0.75 // 28))
        self.assertAlmostEqual(lay["build_cost"], 360 * 6.5 * M)
        self.assertEqual(layout(LOT, 4, shop=True)["units"], int(270 * 0.75 // 28))

    def test_missing_zoning_is_insufficient(self):
        self.assertIsInstance(layout(replace(LOT, buildable_ratio=None), 4), Insufficient)


class Options(unittest.TestCase):
    def test_all_options_built(self):
        o = options(LOT)
        self.assertEqual(set(o), set(OPTION_NAMES))
        self.assertTrue(all(not isinstance(d, Insufficient) for d in o.values()))

    def test_land_counted_at_value_in_every_option(self):
        for name, d in options(LOT).items():
            if d.build_months > 0:
                continue
            up_front = d.price * (1 + d.buy_costs) + d.renovation + d.build_cost
            self.assertAlmostEqual(up_front, LOT.value, delta=1.0, msg=name)

    def test_idle_has_no_income_and_sell_deposit_near_deposit_rate(self):
        o = options(LOT)
        self.assertEqual(o["idle"].rent, 0)
        irr = analyse(o["sell_deposit"])["irr"]
        self.assertLess(irr, LOT.deposit_rate)          # selling costs drag it below the deposit rate
        self.assertGreater(irr, LOT.deposit_rate - 0.01)

    def test_build_loan_is_ltv_of_build_and_jv_has_none(self):
        o = options(LOT)
        self.assertAlmostEqual(o["build_studios"].loan, o["build_studios"].build_cost * 0.5)
        self.assertEqual(o["jv"].loan, 0.0)
        self.assertLess(o["build_small"].build_cost, o["build_studios"].build_cost)

    def test_missing_market_input_is_insufficient_not_defaulted(self):
        o = options(replace(LOT, unit_rent=None, deposit_rate=None))
        self.assertIsInstance(o["build_studios"], Insufficient)
        self.assertIn("unit_rent", o["build_studios"].reason)
        self.assertIsInstance(o["sell_deposit"], Insufficient)
        self.assertNotIsInstance(o["homestay"], Insufficient)

    def test_single_floor_has_no_small_build(self):
        self.assertIsInstance(options(replace(LOT, max_floors=1))["build_small"], Insufficient)


class Evaluate(unittest.TestCase):
    def test_break_even_hits_hurdle(self):
        be = break_even_rent(LOT, "build_studios")
        d = options(LOT)["build_studios"]
        irr = analyse(replace(d, rent=be["rent"]))["irr"]
        self.assertAlmostEqual(irr, LOT.hurdle, places=3)
        self.assertAlmostEqual(be["per_unit"] * be["units"], be["rent"])

    def test_break_even_insufficient_without_income(self):
        self.assertIsInstance(break_even_rent(LOT, "idle"), Insufficient)
        with self.assertRaises(ValueError):
            break_even_rent(LOT, "nope")

    def test_ranking_and_recommendation_from_numbers(self):
        e = evaluate(LOT)
        irrs = [e["options"][k]["irr"] for k in e["ranking"]]
        self.assertEqual(irrs, sorted(irrs, reverse=True))
        rec = e["recommendation"]
        self.assertEqual(rec["option"], e["ranking"][0])
        self.assertIn(f"{e['options'][rec['option']]['irr']:.1%}", rec["reasons"][0])

    def test_jv_owner_proportional_share_matches_unlevered(self):
        d = options(LOT)["jv"]
        share = LOT.value / (LOT.value + d.build_cost + d.renovation)
        o = jv_owner(d, LOT.value, share)
        self.assertAlmostEqual(evaluate(LOT)["options"]["jv"]["owner_share"], share)
        self.assertGreater(jv_owner(d, LOT.value, share + 0.1)["irr"], o["irr"])

    def test_low_dscr_options_excluded(self):
        e = evaluate(replace(LOT, build_ltv=1.0, mortgage_rate=0.25))
        self.assertTrue(any("DSCR" in v for v in e["excluded"].values()))

    def test_no_hurdle_no_recommendation(self):
        e = evaluate(replace(LOT, hurdle=None))
        self.assertIsNone(e["recommendation"])


if __name__ == "__main__":
    unittest.main()
