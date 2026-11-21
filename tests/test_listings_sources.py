import json
import unittest
from pathlib import Path

from vnrealty.listings import sources
from vnrealty.listings.ingest import load_capture
from vnrealty.listings.sources import chotot
from vnrealty.listings.sources._common import read_text_capture, site_id_from_url

FX = Path(__file__).resolve().parent / "fixtures"


def one(rel):
    obs = load_capture(FX / rel)
    return obs


class TestRegistry(unittest.TestCase):
    def test_detect_site(self):
        self.assertEqual(sources.detect_site("https://batdongsan.com.vn/ban-nha-pr1"), "batdongsan")
        self.assertEqual(sources.detect_site("https://www.nhatot.com/123456789.htm"), "chotot")
        self.assertEqual(sources.detect_site("https://xe.chotot.com/x"), "chotot")
        self.assertEqual(sources.detect_site("https://alonhadat.com.vn/a-1.html"), "alonhadat")
        self.assertEqual(sources.detect_site("https://www.facebook.com/groups/1"), "social")
        self.assertEqual(sources.detect_site("https://unknown.vn/x"), "generic")
        for name in ("batdongsan", "chotot", "alonhadat", "guland", "muaban", "bds68", "generic", "social"):
            self.assertIn(name, sources.SITES)

    def test_site_ids(self):
        self.assertEqual(site_id_from_url("https://batdongsan.com.vn/ban-nha-pr41234567", "batdongsan"), "41234567")
        self.assertEqual(site_id_from_url("https://www.facebook.com/groups/1/posts/1234567890/", "facebook"), "1234567890")
        self.assertIsNone(site_id_from_url("https://x.vn/abc", "generic"))

    def test_fixtures_are_marked(self):
        for p in FX.rglob("*.txt"):
            if p.read_text(encoding="utf-8").startswith("#total="):
                continue
            h, _ = read_text_capture(p)
            self.assertIn("fixture", h, p)


class TestTextCaptures(unittest.TestCase):
    def test_batdongsan_detail(self):
        [o] = one("batdongsan/detail.txt")
        self.assertEqual((o.site, o.site_id, o.kind, o.ptype), ("batdongsan", "41234567", "asking", "house"))
        self.assertEqual(o.price, 3.25e9)
        self.assertEqual(o.area_m2, 103)
        self.assertAlmostEqual(o.price_m2, 3.25e9 / 103)
        self.assertEqual((o.frontage_m, o.alley_m, o.floors, o.bedrooms), (5, 5, 3, 4))
        self.assertEqual((o.legal, o.direction, o.corner), ("so_hong", "SE", True))
        self.assertEqual(o.posted_at, "2026-11-08")
        self.assertIn("Hòa Quý", o.address)
        self.assertIsNotNone(o.phone_hash)
        self.assertNotIn("0905", json.dumps(o.extra, ensure_ascii=False) + (o.title or ""))

    def test_batdongsan_search(self):
        a, b = one("batdongsan/search.txt")
        self.assertEqual((a.price, a.area_m2, a.ptype, a.alley_m, a.bedrooms), (2.9e9, 80, "house", 4, 3))
        self.assertEqual(a.extra["search"], "nhs-houses")
        self.assertIn("Mỹ An", a.address)
        self.assertIsNone(b.price)
        self.assertTrue(b.extra["negotiable"])
        self.assertEqual((b.ptype, b.area_m2, b.frontage_m, b.depth_m, b.alley_m, b.legal), ("land", 100, 5, 20, 0.0, "so_do"))
        self.assertEqual(b.posted_at, "2026-11-07")

    def test_chotot_detail(self):
        [o] = one("chotot/detail.txt")
        self.assertEqual((o.site_id, o.price, o.area_m2, o.frontage_m, o.depth_m), ("123456789", 1.95e9, 62, 4.2, 14.8))
        self.assertEqual((o.direction, o.floors, o.bedrooms, o.ptype, o.alley_m), ("NW", 2, 3, "house", 3))
        self.assertEqual(o.legal, "so_hong")      # label says only "Đã có sổ"; the description names the type
        self.assertIn("An Hải Bắc", o.address)

    def test_alonhadat(self):
        [o] = one("alonhadat/detail.txt")
        self.assertEqual((o.site_id, o.price, o.area_m2, o.alley_m, o.legal, o.direction), ("12345678", 4.1e9, 125, 7.5, "so_do", "S"))
        self.assertEqual((o.frontage_m, o.depth_m, o.ptype, o.posted_at), (5, 25, "land", "2026-11-07"))

    def test_other_sites(self):
        [g] = one("guland/detail.txt")
        self.assertEqual((g.price, g.area_m2, g.frontage_m, g.alley_m, g.legal, g.ptype, g.corner), (8.5e8, 300, 10, 4, "so_hong", "land", None))
        [m] = one("muaban/detail.txt")
        self.assertEqual((m.price, m.area_m2, m.bedrooms, m.legal, m.ptype, m.site_id), (2.5e9, 68, 2, "hdmb", "apartment", "71234567"))
        [b] = one("bds68/detail.txt")
        self.assertEqual((b.price, b.area_m2, b.floors, b.alley_m, b.ptype), (18.5e9, 90, 4, 0.0, "house"))
        [r] = one("generic/detail.txt")
        self.assertEqual((r.site, r.kind, r.ptype, r.price, r.area_m2), ("nhadat", "rent", "room", 2.5e6, 20))

    def test_social_text(self):
        obs = one("social/feed.txt")
        self.assertEqual(len(obs), 2)                     # the question post is dropped
        land, rent = obs
        self.assertEqual((land.ptype, land.price, land.area_m2, land.ward_code), ("land", 2.65e9, 100, "ngu-hanh-son"))
        self.assertEqual((rent.kind, rent.price, rent.extra.get("car_access")), ("rent", 15e6, True))


class TestJsonCaptures(unittest.TestCase):
    def test_batdongsan_search_json(self):
        obs = one("batdongsan/search.json")
        self.assertEqual(len(obs), 2)                     # the card without numbers is skipped
        land, house = obs
        self.assertEqual((land.price_m2, land.price, land.frontage_m, land.posted_at), (45e6, 4.5e9, 5, "2026-11-11"))
        self.assertEqual(land.extra["search"], "dn-land")
        self.assertEqual((house.price, house.alley_m, house.site_id), (2.35e9, 3, "40000002"))

    def test_srp_rows(self):
        a, b, c = one("batdongsan/srp.json")
        self.assertEqual((a.site_id, a.ptype, a.price, a.bedrooms, a.posted_at), ("40000011", "house", 3.4e9, 3, "2026-11-13"))
        self.assertEqual((b.kind, b.ptype, b.price), ("rent", "apartment", 9e6))
        self.assertEqual((c.ptype, c.price, c.extra["negotiable"]), ("land", None, True))

    def test_chotot(self):
        [o] = one("chotot/capture.json")
        self.assertEqual((o.kind, o.ptype, o.price, o.lat, o.site_id), ("rent", "apartment", 12e6, 16.0712, "223456789"))

    def test_nhatot_rows(self):
        a, b = chotot.from_rows((FX / "chotot/rows.txt").read_text(encoding="utf-8"))
        self.assertEqual((a.site_id, a.kind, a.ptype, a.price, a.area_m2, a.frontage_m, a.depth_m), ("123450001", "asking", "house", 2.95e9, 72, 4.5, 16))
        self.assertEqual((a.lat, a.lng, a.url), (16.0011, 108.2511, "https://www.nhatot.com/123450001.htm"))
        self.assertEqual((b.kind, b.ptype, b.price, b.lat), ("rent", "apartment", 11e6, None))
        self.assertEqual(chotot.from_rows("garbage"), [])

    def test_social_json(self):
        [o] = one("social/capture.json")
        self.assertEqual((o.site, o.site_id, o.price, o.area_m2, o.legal, o.ward_code), ("facebook", "1234567890", 3.1e9, 72, "so_do", "ngu-hanh-son"))
        self.assertEqual(o.posted_at, "2026-11-02")

    def test_non_listing_kinds(self):
        self.assertEqual(sources.from_capture({"site": "guland_map", "kind": "zoning", "seen_at": "x", "items": [{"raw_text": "ODT"}]}), [])
        self.assertEqual(sources.from_capture({"site": "google_maps", "kind": "map", "seen_at": "x", "items": [{}]}), [])


if __name__ == "__main__":
    unittest.main()
