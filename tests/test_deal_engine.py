"""One property deal: loan phases, rent, the investment metrics, break-evens, the split, the verdict."""
from __future__ import annotations

import unittest
from dataclasses import replace

from vnrealty.deal.engine import Deal, analyse, irr_monthly, schedule, stress

M = 1e6
D = Deal()


class Loan(unittest.TestCase):
    def test_loan_is_repaid_exactly_at_the_end_of_its_term(self):
        rows = schedule(replace(D, term_years=5, hold_years=5))
        self.assertAlmostEqual(rows[-1]["balance"], 0.0, delta=1.0)

    def test_grace_period_pays_interest_only(self):
        rows = schedule(replace(D, grace_months=12))
        self.assertAlmostEqual(rows[11]["balance"], D.loan)
        self.assertAlmostEqual(rows[0]["payment"], D.loan * D.teaser_rate / 12)
        self.assertLess(rows[12]["balance"], D.loan)

    def test_payment_resets_when_the_teaser_ends(self):
        rows = schedule(D)
        self.assertEqual(rows[23]["rate"], D.teaser_rate)
        self.assertEqual(rows[24]["rate"], D.float_rate)
        self.assertGreater(rows[24]["payment"], rows[23]["payment"])

    def test_no_loan_means_no_payments(self):
        self.assertTrue(all(r["payment"] == 0 for r in schedule(replace(D, loan=0.0))))


class Rent(unittest.TestCase):
    def test_no_rent_while_renovating(self):
        rows = schedule(replace(D, lease_up_months=4))
        self.assertEqual(rows[3]["rent"], 0.0)
        self.assertEqual(rows[4]["rent"], D.rent)

    def test_net_operating_income(self):
        r = schedule(replace(D, lease_up_months=0))[0]
        col = D.rent * (1 - D.vacancy)
        self.assertAlmostEqual(r["noi"], col - col * D.management - D.running_costs - col * D.rent_tax)


class Metrics(unittest.TestCase):
    def test_cash_needed_up_front(self):
        a = analyse(D)
        self.assertAlmostEqual(a["cash_in"], D.price * (1 + D.buy_costs) + D.renovation - D.loan)

    def test_profit_split_adds_up(self):
        a = analyse(D)
        self.assertAlmostEqual(sum(a["split"].values()), a["profit"], delta=10.0)

    def test_irr_discounts_to_zero(self):
        cfs = [-100.0] + [1.0] * 119 + [101.0]
        r = irr_monthly(cfs)
        m = (1 + r) ** (1 / 12) - 1
        self.assertAlmostEqual(sum(c / (1 + m) ** t for t, c in enumerate(cfs)), 0.0, places=6)

    def test_break_even_rent_gives_zero_cash_flow(self):
        a = analyse(D)
        b = analyse(replace(D, rent=a["break_even_rent"]))
        self.assertAlmostEqual(b["stable"]["cash"], 0.0, delta=1.0)

    def test_largest_loan_meets_the_coverage_minimum(self):
        a = analyse(D)
        b = analyse(replace(D, loan=a["loan_max"]))
        self.assertAlmostEqual(b["stable"]["dscr"], D.dscr_min, places=6)

    def test_verdict_names_its_reasons(self):
        self.assertTrue(analyse(replace(D, loan=1.0e9))["passes"])
        bad = analyse(replace(D, rent=10 * M))
        self.assertFalse(bad["passes"])
        self.assertIn("cash", bad["reasons"])
        self.assertIn("irr", bad["reasons"])

    def test_stresses_only_make_it_worse(self):
        a, s = analyse(D), stress(D)
        for k in s:
            self.assertLessEqual(s[k]["irr"], a["irr"] + 1e-12, k)


B = replace(D, price=2e9, value_after=2e9, renovation=0.0, build_cost=1.2e9, build_months=12, building_life_years=30,
            loan=1.5e9, lease_up_months=2, teaser_years=0, rent=30e6)
SHOP = replace(B, rent=150e6, ramp_months=6, cogs=0.35, staff=25e6, management=0.0, rent_tax=0.045, vacancy=0.0)


class Construction(unittest.TestCase):
    def test_own_money_first_then_the_loan_draws(self):
        rows = schedule(B)
        own = B.price * (1 + B.buy_costs) + B.build_cost - B.loan       # 1.73B of own money
        land = B.price * (1 + B.buy_costs)                               # 2.03B for the land
        self.assertAlmostEqual(analyse(B)["cash_in"], own)
        # own money does not cover the land, so 0.30B is drawn on day one, then each month's construction
        self.assertAlmostEqual(rows[0]["balance"], land - own + B.build_cost / 12, delta=1.0)
        self.assertAlmostEqual(rows[11]["balance"], B.loan, delta=1.0)

    def test_no_loan_until_own_money_runs_out(self):
        d = replace(B, loan=0.5e9)                                       # own money 2.73B covers land and 0.7B of building
        rows = schedule(d)
        self.assertEqual(rows[0]["balance"], 0.0)
        self.assertGreater(rows[-1]["value"], 0.0)
        self.assertAlmostEqual(rows[11]["balance"], 0.5e9, delta=1.0)

    def test_interest_only_while_building(self):
        rows = schedule(B)
        for r in rows[:12]:
            self.assertAlmostEqual(r["payment"], r["interest"])
        self.assertGreater(rows[12]["principal"], 0.0)

    def test_no_income_until_built_and_let(self):
        rows = schedule(B)
        self.assertEqual(rows[13]["rent"], 0.0)              # month 14: still in lease-up
        self.assertGreater(rows[14]["rent"], 0.0)            # month 15: open

    def test_building_wears_out_while_land_grows(self):
        worn = schedule(B)[-1]["value"]
        kept = schedule(replace(B, building_life_years=0))[-1]["value"]
        self.assertLess(worn, kept)
        land = B.value_after * (1 + B.price_growth) ** (B.hold_years)
        bld = B.build_cost * (1 + B.cost_growth) ** B.hold_years * (1 - (B.hold_years * 12 - 12) / 12 / 30)
        self.assertAlmostEqual(worn, land + bld, delta=10.0)

    def test_split_adds_up_for_a_build(self):
        a = analyse(B)
        self.assertAlmostEqual(sum(a["split"].values()), a["profit"], delta=10.0)

    def test_loan_never_exceeds_the_cost(self):
        a = analyse(replace(B, loan=9e9))
        self.assertAlmostEqual(a["loan_used"], a["cost"])


class Business(unittest.TestCase):
    def test_revenue_ramps_up_after_opening(self):
        rows = schedule(SHOP)
        open_m = SHOP.build_months + SHOP.lease_up_months
        self.assertAlmostEqual(rows[open_m]["rent"], SHOP.rent * (1 + SHOP.rent_growth) / 6)   # month 15 (year 2): 1/6
        self.assertAlmostEqual(rows[open_m + 5]["rent"], SHOP.rent * (1 + SHOP.rent_growth))   # month 20: year 2 prices

    def test_cost_of_goods_and_staff_come_out_of_income(self):
        a = analyse(SHOP)
        col = SHOP.rent
        self.assertAlmostEqual(a["stable"]["noi"], col * (1 - 0.35 - 0.045) - SHOP.running_costs - SHOP.staff)

    def test_break_even_revenue_gives_zero_cash_flow(self):
        a = analyse(SHOP)
        b = analyse(replace(SHOP, rent=a["break_even_rent"]))
        self.assertAlmostEqual(b["stable"]["cash"], 0.0, delta=1.0)

    def test_no_running_costs_or_staff_before_there_is_a_business(self):
        rows = schedule(SHOP)
        self.assertEqual(rows[0]["opex"], 0.0)                               # building
        open_m = SHOP.build_months + SHOP.lease_up_months
        self.assertAlmostEqual(rows[open_m - 1]["opex"], SHOP.running_costs * (1 + SHOP.cost_growth))   # built, not open
        self.assertGreater(rows[open_m]["opex"], rows[open_m - 1]["opex"])                            # staff from opening

    def test_split_adds_up_for_a_business(self):
        a = analyse(SHOP)
        self.assertAlmostEqual(sum(a["split"].values()), a["profit"], delta=10.0)


if __name__ == "__main__":
    unittest.main()
