"""Due-diligence checklist, journal-backed status, and itemised transaction costs from the cited table."""
import unittest

from vnrealty.legal.checklist import ITEMS, checklist, notary_fee, set_status, status, tax_reference, transaction_costs
from vnrealty.store.db import connect
from vnrealty.types import Insufficient


class Items(unittest.TestCase):
    def test_items_bilingual_with_why_and_where(self):
        for i in ITEMS:
            for k in ("id", "vi", "en", "why", "where"):
                self.assertTrue(i[k], (i["id"], k))

    def test_applicability(self):
        apt = {i["id"] for i in checklist("apartment")}
        land = {i["id"] for i in checklist("land")}
        self.assertIn("condo_pink_book", apt)
        self.assertNotIn("permit_as_built", apt)
        self.assertNotIn("condo_pink_book", land)
        self.assertNotIn("foreign_buyer", land)
        self.assertIn("foreign_buyer", {i["id"] for i in checklist("land", foreign=True)})


class Status(unittest.TestCase):
    def test_latest_wins_and_overall(self):
        con = connect(":memory:")
        s = status(con, "lot:x", "land")
        self.assertEqual(s["overall"], "open")
        set_status(con, "lot:x", "zoning", "issue", "road widening 4 m", at="2026-11-01")
        self.assertEqual(status(con, "lot:x", "land")["overall"], "issue")
        set_status(con, "lot:x", "zoning", "ok", "resolved", at="2026-11-02")
        for i in checklist("land"):
            if i["id"] != "zoning":
                set_status(con, "lot:x", i["id"], "ok", at="2026-11-03")
        s = status(con, "lot:x", "land")
        self.assertEqual(s["overall"], "clear")
        z = next(i for i in s["items"] if i["id"] == "zoning")
        self.assertEqual(z["note"], "resolved")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM journal WHERE kind='legal'").fetchone()[0], len(checklist("land")) + 1)

    def test_validation(self):
        con = connect(":memory:")
        with self.assertRaises(ValueError):
            set_status(con, "x", "zoning", "maybe")
        with self.assertRaises(ValueError):
            set_status(con, "x", "astrology", "ok")


class Costs(unittest.TestCase):
    def test_reference_cites_sources(self):
        ref = tax_reference()
        for k in ("registration_fee", "seller_pit", "notary_fee", "developer_vat"):
            self.assertTrue(ref[k]["legal_basis"])
            self.assertTrue(all(u.startswith("http") for u in ref[k]["sources"]))

    def test_notary_tiers(self):
        self.assertEqual(notary_fee(40e6), 50_000)
        self.assertAlmostEqual(notary_fee(500e6), 500_000)
        self.assertAlmostEqual(notary_fee(2e9), 1e6 + 0.0006 * 1e9)
        self.assertAlmostEqual(notary_fee(4e9), 2.2e6 + 0.0005 * 1e9)
        self.assertAlmostEqual(notary_fee(20e9), 5.2e6 + 0.0003 * 10e9)
        self.assertEqual(notary_fee(1e13), 70e6)

    def test_buyer_costs(self):
        r = transaction_costs(3e9, role="buyer")
        it = {i["item"]: i for i in r["items"]}
        self.assertAlmostEqual(it["registration_fee"]["amount"], 15e6)
        self.assertAlmostEqual(r["total"], 15e6 + notary_fee(3e9))

    def test_official_value_raises_the_base_when_higher(self):
        r = transaction_costs(2e9, official_value=2.5e9, role="seller", broker_rate=0.01)
        it = {i["item"]: i for i in r["items"]}
        self.assertAlmostEqual(it["seller_pit"]["amount"], 0.02 * 2.5e9)
        self.assertAlmostEqual(it["broker_fee"]["amount"], 20e6)
        low = transaction_costs(2e9, official_value=1e9, role="seller")
        self.assertAlmostEqual(low["total"], 0.02 * 2e9)

    def test_new_build_vat(self):
        r = transaction_costs(4.4e9, new_build=True)
        vat = next(i for i in r["items"] if i["item"] == "developer_vat")
        self.assertIsInstance(vat["amount"], Insufficient)
        r2 = transaction_costs(4.4e9, new_build=True, land_use_fee=0.0)
        vat2 = next(i for i in r2["items"] if i["item"] == "developer_vat")
        self.assertAlmostEqual(vat2["amount"], 0.4e9)
        self.assertAlmostEqual(r2["total"], r["total"])          # VAT is inside the price, not added
        with self.assertRaises(ValueError):
            transaction_costs(1e9, role="agent")


if __name__ == "__main__":
    unittest.main()
