"""The asset page: per-unit position maths, assembly, and `vnr report asset` end to end (synthetic data only)."""
import json
import tempfile
import unittest
from pathlib import Path

from vnrealty.portfolio.asset import assemble, position
from vnrealty.store.db import connect


class TestPosition(unittest.TestCase):
    def test_share_paid_gain_cagr(self):
        u = {"share": 0.5, "cost": 2e9, "bought_at": "2024-01-01", "area_m2": 100}
        p = position(u, [{"category": "purchase", "amount": -1e9}], 3e9, 0.0, "2026-01-01")
        self.assertEqual(p["own_value"], 1.5e9)
        self.assertEqual(p["paid"], 1e9)
        self.assertEqual(p["paid_basis"], "transactions")
        self.assertEqual(p["gain"], 0.5e9)
        self.assertAlmostEqual(p["cagr"], 1.5 ** (1 / (731 / 365.25)) - 1, places=6)
        self.assertEqual(p["price_m2"], 3e7)
        self.assertEqual(p["equity"], 1.5e9)

    def test_falls_back_to_cost_times_share(self):
        p = position({"share": 0.5, "cost": 2e9, "bought_at": "2024-01-01"}, [], 3e9, None, "2026-01-01")
        self.assertEqual((p["paid"], p["paid_basis"]), (1e9, "cost × share"))
        self.assertIsNone(p["equity"])          # unknown debt is not zero debt

    def test_no_value_means_no_gain(self):
        p = position({"share": 1, "cost": 2e9, "bought_at": "2024-01-01"}, [], None, 0.0, "2026-01-01")
        self.assertIsNone(p["gain"])
        self.assertIsNone(p["cagr"])


class TestAssemble(unittest.TestCase):
    def test_unknown_unit_is_insufficient(self):
        con = connect(":memory:")
        self.assertEqual(type(assemble(con, "nope", "2026-01-01")).__name__, "Insufficient")
        con.close()

    def test_doc_txns_used_only_when_db_has_none(self):
        con = connect(":memory:")
        con.execute("INSERT INTO unit(id, name, share, cost, bought_at) VALUES ('u', 'U', 1, 1e9, '2024-01-01')")
        p = assemble(con, "u", "2026-01-01", doc={"txns": [{"at": "2024-01-01", "category": "purchase", "amount": -1e9}]})
        self.assertEqual(p["txns_source"], "asset document")
        con.execute("INSERT INTO txn(unit_id, at, amount, category) VALUES ('u', '2024-01-01', -1e9, 'purchase')")
        p = assemble(con, "u", "2026-01-01", doc={"txns": [{"at": "x", "category": "purchase", "amount": -5}]})
        self.assertEqual(p["txns_source"], "database")
        con.close()


class TestReportAsset(unittest.TestCase):
    def test_end_to_end(self):
        from vnrealty.cli import main
        d = Path(tempfile.mkdtemp())
        db = d / "vnr.sqlite"
        con = connect(db)
        con.execute("INSERT INTO ward(code, name_vi) VALUES ('w', 'W')")
        for i in range(8):   # comps for the valuation
            con.execute("INSERT INTO listing(id, fingerprint, ptype, deal, ward_code, area_m2, alley_m, lat, lng, first_seen, last_seen) "
                        "VALUES (?, ?, 'land', 'sale', 'w', 100, 4, 16.0, 108.2, '2026-10-01', '2026-11-01')", (i + 1, f"f{i}"))
            con.execute("INSERT INTO listing_obs(listing_id, seen_at, site, kind, price, price_m2) VALUES (?, '2026-11-01', 's', 'asking', ?, ?)",
                        (i + 1, 3e9 + i * 1e8, (3e9 + i * 1e8) / 100))
        con.commit(); con.close()
        main(["--db", str(db), "--json", "unit", "add", "lot1", "Test lot", "--ptype", "land", "--ward", "w", "--area", "100",
              "--lat", "16.0", "--lng", "108.2", "--alley", "4", "--cost", "2000000000", "--share", "0.5", "--bought-at", "2024-01-01",
              "--status", "encroached"])
        main(["--db", str(db), "--json", "txn", "add", "lot1", "-1000000000", "purchase", "--at", "2024-01-01"])
        pdir = d / "portfolio"; pdir.mkdir()
        img = d / "pic.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        (pdir / "lot1.json").write_text(json.dumps({
            "timeline": [{"date": "2024", "event": "bought", "source": "contract"}],
            "actions": [{"step": "recover possession", "status": "todo", "why": "blocks every option"}],
            "images": {"satellite": str(img)}, "gaps": ["loan schedule"],
            "plan_sensitivities": {"3 floors": {"max_floors": 3}}, "project_setup": {"years": 3, "drift": 0.03, "vol": 0.1, "deposit_rate": 0.07}}))
        (pdir / "lot1.plan.json").write_text(json.dumps({"value": 1, "area_m2": 100, "buildable_ratio": 0.9, "max_floors": 4,
                                                         "build_cost_m2": 6.5e6, "unit_size_m2": 27, "unit_rent": 3.5e6, "hurdle": 0.1,
                                                         "deposit_rate": 0.07, "mortgage_rate": 0.12}))
        self.assertEqual(main(["--db", str(db), "--as-of", "2026-11-21", "--json", "report", "asset", "lot1"]), 0)
        html = next((d / "reports").glob("asset-lot1-*.html"), None) or next((d / "reports").glob("asset-*.html"))
        h = html.read_text()
        start = h.index("const DATA = ") + len("const DATA = ")
        data = json.loads(h[start:h.index(";\n", start)].replace("<\\/", "</"))
        heads = [s.get("h") for s in data["sections"]]
        self.assertEqual(data["sections"][0]["tone"], "bad")             # encroached → alert first
        for h_ in ("Position", "Actions", "How the value is built", "Timeline", "Images", "Location and nearby projects"):
            self.assertIn(h_, heads)
        self.assertTrue((d / "reports" / "asset-lot1-files" / "pic.png").exists())
        self.assertIn("PRIVATE", data["meta"])


if __name__ == "__main__":
    unittest.main()
