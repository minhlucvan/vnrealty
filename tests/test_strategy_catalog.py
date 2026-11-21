"""Strategy catalog: every strategy builds on the engine, missing keys are Insufficient, flows agree with the engine."""
import unittest
from dataclasses import replace

from vnrealty.deal.engine import analyse, irr_monthly
from vnrealty.deal.ev import equity_flows
from vnrealty.plan.options import jv_owner
from vnrealty.strategy import catalog as C
from vnrealty.types import Insufficient
from tests.strategy_fixtures import FULL, M, OPP


class Registry(unittest.TestCase):
    def test_all_build_with_full_inputs(self):
        out = C.build_all(OPP, FULL)
        self.assertEqual(set(out), set(C.STRATEGIES))
        for name, sd in out.items():
            self.assertIsInstance(sd, C.StrategyDeal, f"{name}: {sd}")
            m = C.metrics(sd)
            self.assertEqual(m["horizon_months"], len(C.flows(sd)) - 1)

    def test_missing_keys_listed(self):
        a = dict(FULL)
        del a["after_repair_value"], a["flip_renovation"]
        r = C.build("fix_flip", OPP, a)
        self.assertIsInstance(r, Insufficient)
        self.assertIn("after_repair_value", r.reason)
        self.assertIn("flip_renovation", r.reason)

    def test_loan_needs_rate(self):
        r = C.build("buy_hold", OPP, {**FULL, "loan_ltv": 0.5})
        self.assertIsInstance(r, Insufficient)
        self.assertIn("mortgage_rate", r.reason)

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            C.build("nope", OPP, FULL)

    def test_params_carry_basis_and_cover_strategies(self):
        p = C.params()
        for block in [p["common"], *p["defaults"].values()]:
            for k, v in block.items():
                self.assertIn(v["basis"], ("sourced", "partly_sourced", "judgement"), k)
                if v["basis"] != "judgement":
                    self.assertTrue(v.get("sources"), k)
        for name in C.STRATEGIES:
            self.assertGreater(C.liquidity_months(name), 0)
            self.assertTrue(1 <= C.complexity(name) <= 5)
        self.assertEqual(p["tach_thua_da_nang"]["status"], "unverified")


class Parity(unittest.TestCase):
    def test_plain_deal_matches_engine(self):
        sd = C.build("buy_hold", OPP, {**FULL, "loan_ltv": 0.5, "mortgage_rate": 0.10})
        a = analyse(sd.deal)
        m = C.metrics(sd)
        self.assertEqual(C.flows(sd), equity_flows(sd.deal))
        self.assertAlmostEqual(m["irr"], a["irr"], places=9)
        self.assertAlmostEqual(m["npv"], a["npv"], delta=1)
        self.assertAlmostEqual(m["profit"], a["profit"], delta=1)
        self.assertAlmostEqual(m["peak_cash"], a["peak_cash_out"], delta=1)
        self.assertAlmostEqual(m["dscr"], a["stable"]["dscr"])

    def test_long_lease_discount(self):
        sd = C.build("buy_rent_long", OPP, FULL)
        self.assertAlmostEqual(sd.deal.rent, 15 * M * 0.92)
        self.assertAlmostEqual(C.build("buy_rent_long", OPP, {**FULL, "long_lease_rent": 14 * M}).deal.rent, 14 * M)


class Flip(unittest.TestCase):
    def test_hand_checked_unlevered(self):
        sd = C.build("fix_flip", OPP, FULL)
        f = C.flows(sd)
        self.assertEqual(len(f), 7)                                  # 6-month flip (judgement default)
        self.assertAlmostEqual(f[0], -(3e9 * 1.015 + 300 * M))
        self.assertAlmostEqual(f[3], -1.5 * M)
        self.assertAlmostEqual(f[6], -1.5 * M + 3.9e9 * 0.97)
        self.assertAlmostEqual(sum(f), 3.9e9 * 0.97 - 3e9 * 1.015 - 300 * M - 6 * 1.5 * M, delta=1)
        self.assertIsNone(C.metrics(sd)["dscr"])

    def test_loan_interest_only_to_exit(self):
        sd = C.build("fix_flip", OPP, {**FULL, "loan_ltv": 0.5, "mortgage_rate": 0.12})
        f = C.flows(sd)
        self.assertAlmostEqual(f[1], -1.5 * M - 1.5e9 * 0.12 / 12)
        self.assertAlmostEqual(f[6], -1.5 * M - 1.5e9 * 0.01 + 3.9e9 * 0.97 - 1.5e9)


class Subdivide(unittest.TestCase):
    def test_hand_checked(self):
        sd = C.build("subdivide", OPP, FULL)
        self.assertEqual(sd.horizon_months, 15)                      # 9 + 6 (judgement sell months)
        f = C.flows(sd)
        sale = 4 * 45 * 22 * M * 1.05 ** (15 / 12) * 0.97
        self.assertAlmostEqual(f[-1], sale - 3e9 * 0.001 / 12 * 1.04, delta=1)
        self.assertAlmostEqual(f[0], -(3e9 * 1.015 + 250 * M))
        self.assertAlmostEqual(sd.meta["road_m2"], 20)

    def test_refusals(self):
        self.assertIsInstance(C.build("subdivide", OPP, {**FULL, "lots": 5}), Insufficient)       # 225 > 200 m²
        self.assertIsInstance(C.build("subdivide", OPP, {**FULL, "min_lot_m2": 50}), Insufficient)
        a = dict(FULL)
        del a["min_lot_m2"]
        r = C.build("subdivide", OPP, a)
        self.assertIn("min_lot_m2", r.reason)


class Arbitrage(unittest.TestCase):
    def test_deposit_adjusted(self):
        sd = C.build("rental_arbitrage", OPP, FULL)
        d = sd.deal
        self.assertEqual((d.price, d.value_after, d.loan), (0.0, 0.0, 0.0))
        dep = 3 * 25 * M
        eq = equity_flows(d)
        eq[0] -= dep
        eq[-1] += dep
        self.assertEqual(C.flows(sd), eq)
        self.assertAlmostEqual(C.metrics(sd)["irr"], irr_monthly(eq), places=9)
        self.assertAlmostEqual(sd.meta["irr_engine"], analyse(d)["irr"], places=9)
        self.assertAlmostEqual(d.rent, 8 * 6 * M * 0.85)
        self.assertAlmostEqual(d.running_costs, 25 * M)
        self.assertEqual(d.hold_years, 5)

    def test_homestay_mode_and_bad_mode(self):
        sd = C.build("rental_arbitrage", OPP, {**FULL, "sublet_mode": "homestay"})
        self.assertAlmostEqual(sd.deal.management, 0.15)
        self.assertEqual(sd.deal.ramp_months, 6)
        self.assertIsInstance(C.build("rental_arbitrage", OPP, {**FULL, "sublet_mode": "hotel"}), Insufficient)


class OthersTest(unittest.TestCase):
    def test_jv_matches_options_jv_owner(self):
        sd = C.build("joint_venture", OPP, FULL)
        o = jv_owner(sd.deal, 3e9 * 1.015, sd.owner_share)
        self.assertEqual(C.flows(sd), o["flows"])
        self.assertAlmostEqual(C.metrics(sd)["irr"], o["irr"], places=9)
        self.assertEqual(sd.deal.loan, 0.0)

    def test_land_bank_no_income(self):
        sd = C.build("land_bank", OPP, FULL)
        self.assertEqual(sd.deal.rent, 0.0)
        self.assertAlmostEqual(sd.deal.running_costs, 3e9 * 0.001 / 12)
        self.assertAlmostEqual(C.flows(sd)[-1], 3.3e9 * 1.05 ** 8 * 0.97 - sd.deal.running_costs * 1.04 ** 7, delta=1)

    def test_build_to_rent_uses_price_paid(self):
        sd = C.build("build_to_rent", OPP, FULL)
        self.assertEqual(sd.deal.price, 3e9)
        self.assertEqual(sd.deal.value_after, 3.3e9)
        self.assertGreater(sd.deal.build_cost, 0)
        self.assertGreater(sd.meta["units"], 0)

    def test_business_variants(self):
        h = C.build("buy_to_homestay", OPP, FULL).deal
        self.assertAlmostEqual(h.rent, 6 * 700e3 * 365 / 12 * 0.6)
        self.assertEqual((h.vacancy, h.rent_tax, h.renovation), (0.0, 0.07, 400 * M))
        c = C.build("buy_to_chdv", OPP, FULL).deal
        self.assertAlmostEqual(c.rent, 8 * 6 * M * 0.85)
        self.assertEqual(c.staff, 6 * M)


if __name__ == "__main__":
    unittest.main()
