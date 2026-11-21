"""Household affordability (DTI / LTV / DSCR) and the purchase ladder."""
import unittest
from dataclasses import replace

from vnrealty.deal.engine import Deal, analyse
from vnrealty.plan.finplan import Household, affordability, annuity_factor, bank_reference, purchase_plan
from vnrealty.types import Insufficient

M = 1e6
H = Household(cash=1.5e9, monthly_income=60 * M, monthly_spend=25 * M, existing_debt_payment=5 * M,
              emergency_months=6, max_dti=0.4, mortgage_rate=0.10, term_years=20, max_ltv=0.7)


class Affordability(unittest.TestCase):
    def test_dti_loan(self):
        a = affordability(H)
        cap = 0.4 * 60 * M - 5 * M
        self.assertAlmostEqual(a["loan_max_dti"], cap / annuity_factor(0.10, 20))

    def test_max_price_spends_exactly_the_cash(self):
        a = affordability(H)
        self.assertAlmostEqual(a["cash_needed"], H.cash, delta=1.0)
        self.assertLessEqual(a["loan"], a["loan_max_dti"] + 1)
        self.assertLessEqual(a["loan"], 0.7 * a["max_price"] + 1)

    def test_binding_switches_to_dti_when_rich_in_cash(self):
        self.assertEqual(affordability(replace(H, cash=20e9))["binding"], "dti")
        self.assertEqual(affordability(replace(H, cash=0.4e9))["binding"], "ltv")

    def test_cash_below_reserve(self):
        a = affordability(replace(H, cash=100 * M))
        self.assertEqual(a["max_price"], 0.0)
        self.assertEqual(a["binding"], "cash")

    def test_with_deal_three_limits(self):
        d = Deal(loan=2.5e9)
        a = affordability(H, d)
        self.assertEqual(set(a["limits"]), {"dti", "ltv", "dscr"})
        self.assertAlmostEqual(a["limits"]["dscr"], analyse(d)["loan_max"])
        self.assertEqual(a["loan"], min(d.loan, min(a["limits"].values())))
        self.assertTrue(a["loan_cut"])
        self.assertAlmostEqual(a["cash_needed"], a["cost"] - a["loan"] + a["reserve"])

    def test_missing_inputs_insufficient(self):
        r = affordability(replace(H, max_dti=None, mortgage_rate=None))
        self.assertIsInstance(r, Insufficient)
        self.assertIn("max_dti", r.reason)

    def test_reference_is_cited(self):
        ref = bank_reference()
        self.assertEqual(ref["max_dti"]["typical"], 0.40)
        self.assertTrue(all(e["url"].startswith("http") for e in ref["max_dti"]["evidence"]))


class Plan(unittest.TestCase):
    def test_ladder_and_first_purchase_date(self):
        d = Deal(price=2e9, value_after=2.1e9, loan=1e9, rent=14 * M)
        p = purchase_plan(replace(H, cash=2e9), d, years=10, start="2027-01")
        self.assertAlmostEqual(p["save_month"], 30 * M)
        self.assertGreaterEqual(p["n_buys"], 1)
        self.assertEqual(p["first_buy_month"], 0)
        self.assertEqual(p["first_buy_date"], "2027-01")
        self.assertLessEqual(p["unit_loan"], d.loan)

    def test_no_purchase_reports_none(self):
        d = Deal(price=20e9, value_after=20e9, loan=10e9, rent=30 * M)
        p = purchase_plan(replace(H, cash=0.5e9), d, years=3, start="2027-01")
        self.assertIsNone(p["first_buy_date"])
        self.assertTrue(p["blocked"])

    def test_insufficient_passthrough(self):
        self.assertIsInstance(purchase_plan(replace(H, cash=None), Deal(), 5), Insufficient)


if __name__ == "__main__":
    unittest.main()
