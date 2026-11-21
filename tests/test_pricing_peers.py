import unittest

from tests import pricing_fixtures as F
from vnrealty.pricing import peers
from vnrealty.types import Insufficient


def tearDownModule():
    F.close_all()


class TestUnits(unittest.TestCase):
    def test_unit_for_type(self):
        self.assertEqual(peers.unit_for("land"), "price_m2")
        self.assertEqual(peers.unit_for("apartment"), "price_m2_floor")
        self.assertEqual(peers.unit_for("shophouse"), "price_per_frontage_m")
        self.assertEqual(peers.unit_for("chdv"), "price_per_room")
        self.assertEqual(peers.unit_for("house", "rent"), "rent_m2")

    def test_unit_value(self):
        r = {"price": 1e9, "area_m2": 100, "frontage_m": 4, "bedrooms": 5, "ptype": "apartment"}
        self.assertEqual(peers.unit_value(r, "price_m2"), 1e7)
        self.assertEqual(peers.unit_value(r, "price_m2_floor"), 1e7)  # apartment: area is floor area
        self.assertEqual(peers.unit_value(r, "price_per_frontage_m"), 2.5e8)
        self.assertEqual(peers.unit_value(r, "price_per_room"), 2e8)
        self.assertEqual(peers.unit_value({**r, "extra": '{"rooms": 10}'}, "price_per_room"), 1e8)
        self.assertIsNone(peers.unit_value({**r, "price": None}, "price_m2"))
        self.assertIsNone(peers.unit_value({**r, "ptype": "house"}, "price_m2_floor"))

    def test_project_key(self):
        self.assertEqual(peers.project_key("Bán căn hộ Monarchy B view sông Hàn"), "monarchy b")
        self.assertEqual(peers.project_key("Chung cư Hiyori Garden Tower 2PN"), "hiyori garden tower")
        self.assertIsNone(peers.project_key("Bán nhà kiệt 3m"))


class TestPeerStats(unittest.TestCase):
    def test_stats_percentile_and_robust_z(self):
        con = F.db()
        F.spread(con, 11, lo=40e6, hi=60e6)  # 40..60 step 2 M/m²
        subj = {"ptype": "land", "ward_code": "w-a", "area_m2": 100, "price": 4.0e9, "deal": "sale"}
        ps = peers.peer_stats(con, subj, "2026-11-01")
        self.assertEqual((ps["scope"], ps["n"]), ("ward", 11))
        self.assertAlmostEqual(ps["median"], 50e6)
        self.assertAlmostEqual(ps["percentile"], 100 * 0.5 / 11)  # ties with the lowest peer
        mad = 6e6  # |x − 50| over 40..60 step 2 → median 6
        self.assertAlmostEqual(ps["z"], (40e6 - 50e6) / (1.4826 * mad))

    def test_subject_excluded_and_pit(self):
        con = F.db()
        ids = F.spread(con, 8, lo=40e6, hi=60e6)
        F.add(con, area=100, obs=(("2026-12-01", 1e9),))  # future observation: invisible at as_of
        ps = peers.peer_stats(con, ids[0], "2026-11-01", min_n=7)
        self.assertEqual(ps["n"], 7)
        self.assertIsInstance(peers.peer_stats(con, ids[0], "2026-11-01", min_n=8), Insufficient)

    def test_latest_observation_per_listing(self):
        con = F.db()
        F.spread(con, 8, lo=50e6, hi=50e6)
        F.add(con, area=100, obs=(("2026-09-01", 9e9), ("2026-10-15", 3e9)))
        ps = peers.peer_stats(con, {"ptype": "land", "ward_code": "w-a", "area_m2": 100}, "2026-11-01")
        self.assertEqual(ps["n"], 9)
        self.assertLess(min([3e7]), ps["median"])
        self.assertIsNone(ps["percentile"])  # subject without a price

    def test_ladder_widens_scope(self):
        con = F.db()
        F.spread(con, 3, ward="w-a")
        F.spread(con, 6, ward="w-b")
        F.spread(con, 10, ward="w-c")
        subj = {"ptype": "land", "ward_code": "w-a", "area_m2": 100, "price": 5e9}
        ps = peers.peer_stats(con, subj, "2026-11-01")
        self.assertEqual((ps["scope"], ps["place"], ps["n"]), ("old_district", "D1", 9))
        ps = peers.peer_stats(con, subj, "2026-11-01", min_n=12)
        self.assertEqual((ps["scope"], ps["n"]), ("city", 19))
        bad = peers.peer_stats(con, subj, "2026-11-01", min_n=50)
        self.assertIsInstance(bad, Insufficient)
        self.assertEqual([s["scope"] for s in bad.detail["ladder"]], ["ward", "old_district", "city"])

    def test_area_band_then_wider_band(self):
        con = F.db()
        F.spread(con, 8, area=100)
        F.spread(con, 8, area=150)   # outside (80, 125) m², inside the wide band (53, 187.5) m²
        F.spread(con, 8, area=400)   # outside both
        subj = {"ptype": "land", "ward_code": "w-a", "area_m2": 100, "price": 5e9}
        ps = peers.peer_stats(con, subj, "2026-11-01", area_band=(0.8, 1.25))
        self.assertEqual((ps["scope"], ps["n"]), ("ward", 8))
        ps = peers.peer_stats(con, subj, "2026-11-01", area_band=(0.8, 1.25), min_n=16)
        self.assertEqual((ps["scope"], ps["n"]), ("ward_wide_band", 16))

    def test_project_scope_first(self):
        con = F.db()
        F.spread(con, 5, ptype="apartment", area=60, lo=60e6, hi=70e6, title="Bán căn hộ Monarchy B view sông")
        F.spread(con, 10, ptype="apartment", area=60, lo=30e6, hi=40e6, title="Bán căn hộ giá rẻ")
        subj = {"ptype": "apartment", "ward_code": "w-a", "area_m2": 60, "price": 60 * 65e6}
        ps = peers.peer_stats(con, subj, "2026-11-01", project="monarchy b", project_min_n=5)
        self.assertEqual((ps["scope"], ps["n"]), ("project", 5))
        ps = peers.peer_stats(con, subj, "2026-11-01")
        self.assertEqual(ps["n"], 15)

    def test_snapshot_history(self):
        con = F.db()
        lid = F.add(con, obs=(("2026-05-01", None), ("2026-06-01", 6e9), ("2026-08-01", 5.4e9), ("2026-12-01", 4e9)))
        s = peers.snapshot(con, lid, "2026-11-01")
        self.assertEqual(s["price"], 5.4e9)
        self.assertEqual(s["days_on_market"], 184)
        self.assertEqual(s["cuts"], 1)
        self.assertAlmostEqual(s["cut_total"], -0.1)
        self.assertTrue(s["negotiable"])
        self.assertIsInstance(peers.snapshot(con, lid, "2026-01-01"), Insufficient)

    def test_cache_reused(self):
        con = F.db()
        F.spread(con, 9)
        c = peers.PeerCache(con, "2026-11-01")
        subj = {"ptype": "land", "ward_code": "w-a", "area_m2": 100, "price": 5e9}
        a = peers.peer_stats(con, subj, "2026-11-01", cache=c)
        F.add(con, area=100)  # added after the pool was cached
        b = peers.peer_stats(con, subj, "2026-11-01", cache=c)
        self.assertEqual(a["n"], b["n"])


if __name__ == "__main__":
    unittest.main()
