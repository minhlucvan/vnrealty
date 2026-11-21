"""Month-end close: paid / partial / overdue / due, days late, expenses, renewals, deposits, alerts."""
import unittest

from vnrealty.portfolio.ops import monthly_close
from vnrealty.portfolio.units import add_lease, add_txn, add_unit
from vnrealty.store.db import connect

M = 1e6


def seed():
    con = connect(":memory:")
    for u in ("a", "b", "c", "d"):
        add_unit(con, u, f"unit {u}")
    la = add_lease(con, "a", "2026-01-01", 5 * M, due_day=5, deposit=10 * M, end="2026-12-15")
    lb = add_lease(con, "b", "2026-01-01", 6 * M, due_day=10, deposit=12 * M)
    lc = add_lease(con, "c", "2026-01-01", 7 * M, due_day=31)
    add_txn(con, "2026-11-08", 5 * M, "rent", "a", la, period="2026-11")
    add_txn(con, "2026-11-12", 2 * M, "rent", "b", lb)
    add_txn(con, "2026-11-20", -3 * M, "repair", "a")
    add_txn(con, "2026-11-21", -1 * M, "utility", "b")
    return con, la, lb, lc


class Close(unittest.TestCase):
    def test_statuses_and_days_late(self):
        con, la, lb, lc = seed()
        r = monthly_close(con, "2026-11", as_of="2026-11-25")
        by = {l["lease_id"]: l for l in r["rent"]}
        self.assertEqual((by[la]["status"], by[la]["days_late"]), ("paid", 3))
        self.assertEqual((by[lb]["status"], by[lb]["outstanding"], by[lb]["days_late"]), ("partial", 4 * M, 15))
        self.assertEqual(by[lc]["status"], "due")                 # due day 31 clamps to 30, not yet due
        self.assertEqual(by[lc]["due_date"], "2026-11-30")
        self.assertAlmostEqual(r["expected_rent"], 18 * M)
        self.assertAlmostEqual(r["received_rent"], 7 * M)

    def test_month_end_overdue_expenses_and_alerts(self):
        con, la, lb, lc = seed()
        r = monthly_close(con, "2026-12")
        by = {l["lease_id"]: l["status"] for l in r["rent"]}
        self.assertEqual(by, {la: "overdue", lb: "overdue", lc: "due"})   # c is due on the 31st itself
        n = monthly_close(con, "2026-11", as_of="2026-11-25")
        self.assertEqual(n["expenses"], {"repair": -3 * M, "utility": -1 * M})
        self.assertAlmostEqual(n["net_cash"], 3 * M)
        self.assertAlmostEqual(n["deposits_held"], 22 * M)
        self.assertEqual([x["lease_id"] for x in n["renewals"]], [la])
        kinds = {a["kind"] for a in n["alerts"]}
        self.assertTrue({"rent_partial", "renewal_due", "vacant"} <= kinds)

    def test_lease_ended_before_due_date_owes_nothing(self):
        con, la, lb, lc = seed()
        r = monthly_close(con, "2026-12", as_of="2026-12-31")
        self.assertIn(la, {l["lease_id"] for l in r["rent"]})       # ends 12-15, due 12-05: owes December
        r2 = monthly_close(con, "2027-01", as_of="2027-01-31")
        self.assertNotIn(la, {l["lease_id"] for l in r2["rent"]})


if __name__ == "__main__":
    unittest.main()
