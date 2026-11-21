"""The portfolio ladder. Anchor: one unit held to the deal's horizon reproduces analyse() exactly."""
from __future__ import annotations

import unittest
from dataclasses import replace

from vnrealty.deal.engine import Deal, analyse
from vnrealty.deal.scale import Scale, scale_run

D = replace(Deal(), dscr_min=0.0)   # Deal()'s own DSCR is ~1.17, under its 1.2 floor
SOLO = Scale(cash0=5e9, save_month=0, horizon_years=Deal().hold_years, max_units=1, reserve_months=0, refi_years=0, ltv_cap=1,
             mgr_every=0, last_buy_years=0)


class TestScale(unittest.TestCase):
    def test_single_unit_reproduces_analyse(self):
        for d in (D, replace(D, loan=0.0),
                  replace(D, price=2e9, value_after=2e9, renovation=0.0, build_cost=1.2e9, build_months=12, building_life_years=30, loan=1.5e9, rent=30e6),
                  replace(D, grace_months=12, teaser_years=3, lease_up_months=6, hold_years=12)):
            r = scale_run(d, replace(SOLO, horizon_years=d.hold_years))
            self.assertEqual(len(r["buys"]), 1)
            self.assertAlmostEqual(r["end"]["net_worth"] - SOLO.cash0, analyse(d)["profit"], delta=1.0)

    def test_over_borrowed_unit_bought_with_loan_cut_to_floor(self):
        d = Deal(); a = analyse(d)
        self.assertLess(a["stable"]["dscr"], d.dscr_min)
        r = scale_run(d, SOLO)
        self.assertEqual(len(r["buys"]), 1)
        self.assertAlmostEqual(r["buys"][0]["loan"], a["loan_max"], delta=1.0)
        self.assertAlmostEqual(r["buys"][0]["dscr"], d.dscr_min, places=6)

    def test_no_cash_no_purchase(self):
        r = scale_run(D, replace(SOLO, cash0=1e8))
        self.assertEqual(r["end"]["units"], 0)
        self.assertGreater(r["blocked"]["cash"], 0)

    def test_negative_noi_never_bought(self):
        r = scale_run(replace(D, dscr_min=1.2, rent=1e6), SOLO)
        self.assertEqual(len(r["buys"]), 0)
        self.assertGreater(r["blocked"]["noi"], 0)

    def test_ltv_cap_blocks(self):
        r = scale_run(D, replace(SOLO, ltv_cap=0.2))
        self.assertEqual(len(r["buys"]), 0)
        self.assertGreater(r["blocked"]["ltv"], 0)

    def test_more_savings_never_fewer_units(self):
        base = replace(SOLO, cash0=2e9, max_units=10, horizon_years=15, last_buy_years=2)
        lo, hi = scale_run(D, replace(base, save_month=10e6)), scale_run(D, replace(base, save_month=60e6))
        self.assertGreaterEqual(hi["end"]["units"], lo["end"]["units"])
        self.assertGreater(hi["end"]["units"], 1)

    def test_refinance(self):
        r = scale_run(D, replace(SOLO, refi_years=5, refi_ltv=0.7))
        m, prev = r["months"][60], r["months"][59]
        self.assertGreater(m["refi_in"], 0)
        self.assertGreater(m["debt"], prev["debt"])
        self.assertAlmostEqual(m["debt"] / m["value"], 0.7, places=9)

    def test_managers(self):
        r = scale_run(D, replace(SOLO, cash0=50e9, max_units=9, mgr_every=4, mgr_cost=10e6, horizon_years=10))
        at = lambda k: next(m for m in r["months"] if m["units"] == k)  # noqa: E731
        self.assertEqual((at(4)["managers"], at(5)["managers"], at(9)["managers"]), (0, 1, 2))


if __name__ == "__main__":
    unittest.main()
