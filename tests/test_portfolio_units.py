"""Units, leases, txns, rent roll, occupancy and the financial summary (in-memory DB)."""
import unittest

from vnrealty.portfolio.units import (add_lease, add_months, add_txn, add_unit, annuity_balance, annuity_payment,
                                      end_lease, list_units, months_between, occupancy, rent_roll, summary, update_unit)
from vnrealty.store.db import connect

M = 1e6


def seed():
    con = connect(":memory:")
    add_unit(con, "u1", "Studio block", ptype="chdv", ward_code="w1", bought_at="2025-01-15", cost=4e9, share=0.5,
             loan=2e9, loan_rate=0.10, loan_term_years=20, value=5e9, value_at="2026-06-01", legal="so_hong")
    add_unit(con, "u2", "Apartment", ptype="apartment", ward_code="w2", bought_at="2024-03-01", cost=2e9, value=2.4e9,
             legal="hdmb")
    l1 = add_lease(con, "u1", "2025-06-01", 40 * M, end="2027-05-31", deposit=80 * M, due_day=5, tenant="T1")
    for m in range(1, 13):
        add_txn(con, f"2026-{m:02d}-05", 20 * M, "rent", "u1", l1, period=f"2026-{m:02d}")
        add_txn(con, f"2026-{m:02d}-10", -2 * M, "repair", "u1")
        add_txn(con, f"2026-{m:02d}-15", -9 * M, "loan_interest", "u1")
    add_txn(con, "2026-03-01", 80 * M, "deposit", "u1", l1)
    return con


class Helpers(unittest.TestCase):
    def test_annuity_balance_ends_at_zero_and_matches_payment(self):
        self.assertAlmostEqual(annuity_balance(1e9, 0.1, 10, 120), 0.0)
        p = annuity_payment(1e9, 0.1, 10)
        bal, r = 1e9, 0.1 / 12
        for _ in range(37):
            bal = bal * (1 + r) - p
        self.assertAlmostEqual(annuity_balance(1e9, 0.1, 10, 37), bal, delta=1e-3)
        self.assertAlmostEqual(annuity_balance(1.2e9, 0.0, 10, 60), 0.6e9)

    def test_months(self):
        self.assertEqual(months_between("2025-01-15", "2026-01-14"), 11)
        self.assertEqual(months_between("2025-01-15", "2026-01-15"), 12)
        self.assertEqual(add_months("2026-03-31", -1), "2026-02-28")


class Records(unittest.TestCase):
    def test_crud_and_validation(self):
        con = seed()
        update_unit(con, "u2", status="sold")
        self.assertEqual([u["id"] for u in list_units(con, "held")], ["u1"])
        with self.assertRaises(KeyError):
            update_unit(con, "nope", name="x")
        with self.assertRaises(ValueError):
            add_unit(con, "u3", "x", colour="red")
        with self.assertRaises(ValueError):
            add_txn(con, "2026-01-01", 1, "bribe")

    def test_rent_roll_and_occupancy(self):
        con = seed()
        rr = rent_roll(con, "2026-11-21")
        self.assertEqual(len(rr), 1)
        self.assertEqual(rr[0]["rent"], 40 * M)
        occ = occupancy(con, "2026-11-21")
        self.assertEqual((occ["let"], occ["held"], occ["vacant"]), (1, 2, ["u2"]))
        end_lease(con, rr[0]["lease_id"], "2026-10-31")
        self.assertEqual(rent_roll(con, "2026-11-21"), [])


class Summary(unittest.TestCase):
    def test_per_unit_numbers(self):
        con = seed()
        s = summary(con, "2026-12-31")
        u1 = next(u for u in s["units"] if u["id"] == "u1")
        self.assertAlmostEqual(u1["value"], 2.5e9)                               # 5e9 × 0.5
        bal = annuity_balance(2e9, 0.10, 20, months_between("2025-01-15", "2026-12-31"))
        self.assertAlmostEqual(u1["debt"], bal * 0.5)
        self.assertAlmostEqual(u1["noi_ttm"], 12 * 18 * M)                       # deposit and interest excluded
        self.assertAlmostEqual(u1["debt_service_ttm"], 12 * 9 * M)
        self.assertAlmostEqual(u1["yield_on_value"], 216 * M / 2.5e9)
        self.assertAlmostEqual(u1["cash_on_cash"], (216 - 108) * M / ((4e9 - 2e9) * 0.5))

    def test_valuation_table_wins_and_point_in_time(self):
        con = seed()
        con.execute("INSERT INTO valuation(subject, as_of, method, value, created_at) VALUES ('unit:u2','2026-09-01','comps',2.6e9,'x')")
        s = summary(con, "2026-12-31")
        self.assertAlmostEqual(next(u for u in s["units"] if u["id"] == "u2")["value"], 2.6e9)
        s0 = summary(con, "2026-01-01")                                          # before value_at of u1
        u1 = next(u for u in s0["units"] if u["id"] == "u1")
        self.assertIsNone(u1["value"])
        self.assertTrue(any(g["unit"] == "u1" for g in s0["gaps"]))
        self.assertFalse(s0["total"]["complete"])

    def test_loan_without_terms_is_a_gap(self):
        con = connect(":memory:")
        add_unit(con, "x", "x", loan=1e9, value=2e9, bought_at="2025-01-01")
        s = summary(con, "2026-01-01")
        self.assertIsNone(s["units"][0]["debt"])
        self.assertIn("loan_rate", s["gaps"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
