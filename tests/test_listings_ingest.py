import json
import shutil
import tempfile
import unittest
from pathlib import Path

from vnrealty.listings.ingest import ingest, ingest_dir, ingest_file
from vnrealty.store.db import connect
from vnrealty.types import ListingObs

FX = Path(__file__).resolve().parent / "fixtures"


def o(**kw):
    base = dict(site="batdongsan", seen_at="2026-11-01T10:00:00", ptype="house", area_m2=100.0, frontage_m=5.0,
                address="Kiệt 12 Lê Văn Hiến, Phường Hòa Quý", price=3.2e9)
    base.update(kw)
    return ListingObs(**base)


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.con = connect(":memory:")
        self.addCleanup(self.con.close)

    def test_new_then_update(self):
        s = ingest(self.con, [o(site_id="1")], "raw/a.json")
        self.assertEqual(s, {"new_listings": 1, "new_obs": 1, "updated": 0, "duplicate_obs": 0})
        l = dict(self.con.execute("SELECT * FROM listing").fetchone())
        self.assertEqual((l["ward_code"], l["street"], l["status"]), ("ngu-hanh-son", "le van hien", "active"))
        ob = dict(self.con.execute("SELECT * FROM listing_obs").fetchone())
        self.assertAlmostEqual(ob["price_m2"], 3.2e7)
        self.assertEqual(ob["raw_ref"], "raw/a.json")
        # same site id later, a cut, and a new attribute → same listing, first_seen kept, blank filled
        s = ingest(self.con, [o(site_id="1", seen_at="2026-11-05T10:00:00", price=3.0e9, bedrooms=4, legal="so_do",
                                frontage_m=None)], "raw/b.json")
        self.assertEqual((s["new_listings"], s["new_obs"], s["updated"]), (0, 1, 1))
        l = dict(self.con.execute("SELECT * FROM listing").fetchone())
        self.assertEqual((l["first_seen"], l["last_seen"], l["bedrooms"], l["legal"], l["frontage_m"]),
                         ("2026-11-01T10:00:00", "2026-11-05T10:00:00", 4, "so_do", 5.0))

    def test_never_overwrite_existing_attribute(self):
        ingest(self.con, [o(site_id="1", bedrooms=3)])
        ingest(self.con, [o(site_id="1", seen_at="2026-11-02", bedrooms=5)])
        self.assertEqual(self.con.execute("SELECT bedrooms FROM listing").fetchone()[0], 3)

    def test_cross_site_merge_and_negotiable(self):
        ingest(self.con, [o(site_id="1"), o(site="chotot", site_id="77", price=None, address="K45 Lê Văn Hiến, Hoà Quý")])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM listing").fetchone()[0], 1)
        prices = [r[0] for r in self.con.execute("SELECT price FROM listing_obs ORDER BY site")]
        self.assertEqual(prices, [3.2e9, None])

    def test_duplicate_obs_and_unknown_ward(self):
        ingest(self.con, [o(site_id="1")])
        s = ingest(self.con, [o(site_id="1")])
        self.assertEqual(s["duplicate_obs"], 1)
        s = ingest(self.con, [o(site_id="2", address="Somewhere, Hà Nội", ward_code="not-a-ward", area_m2=50)])
        self.assertEqual(s["new_listings"], 1)
        self.assertIsNone(self.con.execute("SELECT ward_code FROM listing WHERE area_m2=50").fetchone()[0])

    def test_gone_reactivated(self):
        ingest(self.con, [o(site_id="1")])
        self.con.execute("UPDATE listing SET status='gone'")
        ingest(self.con, [o(site_id="1", seen_at="2026-12-20")])
        self.assertEqual(self.con.execute("SELECT status FROM listing").fetchone()[0], "active")

    def test_files_and_dir(self):
        s = ingest_file(self.con, FX / "batdongsan" / "detail.txt")
        self.assertEqual((s["parsed"], s["new_listings"]), (1, 1))
        raw = self.con.execute("SELECT raw_ref, extra FROM listing_obs").fetchone()
        self.assertTrue(raw["raw_ref"].endswith("detail.txt"))
        self.assertNotIn("0905", raw["extra"])
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(FX, Path(d) / "fx")
            (Path(d) / "fx" / "zoning.json").write_text(json.dumps({"site": "guland_map", "kind": "zoning",
                                                                     "seen_at": "2026-11-01", "items": []}))
            (Path(d) / "fx" / "bad.json").write_text("{not json")
            con = connect(":memory:")
            t = ingest_dir(con, Path(d) / "fx")
            self.assertEqual(len(t["errors"]), 1)
            self.assertGreaterEqual(t["new_listings"], 15)
            again = ingest_dir(con, Path(d) / "fx")
            self.assertEqual((again["new_listings"], again["new_obs"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
