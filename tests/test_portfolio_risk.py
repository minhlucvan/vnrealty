"""Risk report: concentration, LTV, DSCR, liquidity, shocks, flags with numbers, zoning convention."""
import unittest

from vnrealty.portfolio.risk import hhi, risk_report, zoning_flags
from vnrealty.portfolio.units import add_txn, add_unit, annuity_balance, annuity_payment, months_between
from vnrealty.store.db import connect

M = 1e6


def seed():
    con = connect(":memory:")
    add_unit(con, "a", "A", ptype="house", ward_code="w1", bought_at="2026-01-01", cost=3e9, loan=2e9, loan_rate=0.10,
             loan_term_years=20, value=3e9, legal="so_hong", notes="corner lot; zoning:road_widening")
    add_unit(con, "b", "B", ptype="apartment", ward_code="w1", bought_at="2025-01-01", cost=1e9, value=1e9, legal="hdmb",
             notes="zoning:ok")
    for m in range(1, 13):
        add_txn(con, f"2026-{m:02d}-05", 15 * M, "rent", "a")
        add_txn(con, f"2026-{m:02d}-06", -1 * M, "repair", "a")
    return con


class Helpers(unittest.TestCase):
    def test_hhi(self):
        h = hhi({"x": 3, "y": 1})
        self.assertAlmostEqual(h["hhi"], 0.75 ** 2 + 0.25 ** 2)
        self.assertEqual((h["top"], h["top_share"]), ("x", 0.75))
        self.assertIsNone(hhi({})["hhi"])

    def test_zoning_tokens(self):
        self.assertEqual(zoning_flags("x zoning:clearance and zoning:ok, zoning:green_space"), ["clearance", "green_space"])
        self.assertEqual(zoning_flags(None), [])


class Report(unittest.TestCase):
    def test_core_numbers(self):
        con = seed()
        r = risk_report(con, "2026-12-31", cash=100 * M)
        bal = annuity_balance(2e9, 0.10, 20, months_between("2026-01-01", "2026-12-31"))
        pay = annuity_payment(2e9, 0.10, 20)
        self.assertAlmostEqual(r["ltv"], bal / 4e9)
        self.assertAlmostEqual(r["dscr"], 12 * 14 * M / (12 * pay))
        self.assertAlmostEqual(r["liquidity_months"], 100 * M / (pay + 1 * M))
        self.assertAlmostEqual(r["concentration"]["ward"]["hhi"], 1.0)
        self.assertAlmostEqual(r["concentration"]["ptype"]["top_share"], 0.75)

    def test_shocks(self):
        con = seed()
        r = risk_report(con, "2026-12-31", cash=100 * M)
        rates = r["shocks"]["rates"]
        self.assertEqual([x["rate_up"] for x in rates], [0.02, 0.03])
        self.assertGreater(rates[1]["monthly_payment"], rates[0]["monthly_payment"])
        self.assertGreater(rates[0]["monthly_payment"], r["monthly_debt_service"])
        self.assertAlmostEqual(r["shocks"]["prices"][1]["ltv"], r["debt"] / (r["value"] * 0.7))
        self.assertAlmostEqual(r["shocks"]["vacancy"][0]["noi"], 168 * M - 0.2 * 180 * M)
        r2 = risk_report(con, "2026-12-31", cash=1e9, stress={"rate_up": [0.05]})
        self.assertEqual(len(r2["shocks"]["rates"]), 1)

    def test_flags_carry_numbers(self):
        con = seed()
        r = risk_report(con, "2026-12-31", cash=100 * M)
        f = {(x["code"], x["unit"]): x for x in r["flags"]}
        self.assertEqual(f[("legal_title", "b")]["value"], "hdmb")
        self.assertEqual(f[("zoning", "a")]["value"], "road_widening")
        self.assertNotIn(("zoning", "b"), f)
        self.assertAlmostEqual(f[("dscr", None)]["value"], r["dscr"])
        self.assertAlmostEqual(f[("liquidity", None)]["value"], r["liquidity_months"])
        self.assertIn(("unit_ltv", "a"), f)
        self.assertNotIn(("ltv", None), f)                       # portfolio LTV ~0.49 < 0.6

    def test_missing_value_is_a_gap_flag(self):
        con = seed()
        add_unit(con, "c", "C", value=None, legal="so_do")
        r = risk_report(con, "2026-12-31", cash=1e9)
        self.assertTrue(any(x["code"] == "data_gap" and x["unit"] == "c" for x in r["flags"]))


if __name__ == "__main__":
    unittest.main()
