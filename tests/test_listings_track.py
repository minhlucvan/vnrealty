import unittest

from vnrealty.listings import track
from vnrealty.listings.ingest import ingest
from vnrealty.store.db import connect
from vnrealty.types import ListingObs


def o(sid, seen, price, site="batdongsan", search=None, **kw):
    x = {"search": search} if search else {}
    kw.setdefault("area_m2", 100.0)
    return ListingObs(site=site, site_id=sid, seen_at=seen, price=price, ptype="house", extra=x, **kw)


class TestTrack(unittest.TestCase):
    def setUp(self):
        self.con = connect(":memory:")
        self.addCleanup(self.con.close)
        ingest(self.con, [o("1", "2026-09-01", 3.0e9), o("1", "2026-10-01", 2.8e9), o("1", "2026-10-15", 2.9e9),
                          o("2", "2026-10-10", 1.0e9), o("3", "2026-06-01", 5e9), o("3", "2026-10-20", 5e9)])
        # same property quoted higher on a second site — must not read as a raise/cut
        ingest(self.con, [ListingObs(site="chotot", site_id="x1", seen_at="2026-10-05", price=3.5e9, ptype="house",
                                     area_m2=100.0)])

    def lid(self, sid):
        return self.con.execute("SELECT listing_id FROM listing_obs WHERE site_id=?", (sid,)).fetchone()[0]

    def test_history(self):
        h = track.history(self.con, self.lid("1"))
        self.assertEqual([r["price"] for r in h], [3.0e9, 2.8e9, 2.9e9])

    def test_changes(self):
        c = track.changes(self.con, "2026-09-15", "2026-10-31")
        [cut] = c["cuts"]
        self.assertEqual((cut["from"], cut["to"], cut["vnd"]), (3.0e9, 2.8e9, -2e8))
        self.assertAlmostEqual(cut["pct"], -2 / 30)
        [raise_] = c["raises"]
        self.assertEqual(raise_["to"], 2.9e9)
        self.assertIn(self.lid("2"), c["new"])
        self.assertIn(self.lid("3"), c["relisted"])
        self.assertNotIn(self.lid("1"), c["new"])

    def test_changes_point_in_time(self):
        c = track.changes(self.con, "2026-09-15", "2026-10-05")
        self.assertEqual(len(c["cuts"]), 1)
        self.assertEqual(c["raises"], [])

    def test_searches_and_mark_gone(self):
        sid = track.add_search(self.con, "nhs", "batdongsan", "https://batdongsan.com.vn/ban-nha-ngu-hanh-son", {"ptype": "house"})
        self.assertEqual(track.add_search(self.con, "nhs", "batdongsan", "https://x"), sid)
        self.assertEqual(track.list_searches(self.con)[0]["url"], "https://x")
        ingest(self.con, [o("10", "2026-08-01", 2e9, search="nhs", area_m2=None), o("11", "2026-08-01", 2e9, area_m2=None)])
        a, b = self.lid("10"), self.lid("11")
        self.assertEqual(track.mark_gone(self.con, "2026-10-01"), [])        # search never re-run
        track.touch_search(self.con, "nhs", "2026-09-20")
        gone = track.mark_gone(self.con, "2026-10-01")
        self.assertEqual(gone, [a])                                            # b was not from a saved search
        st = dict(self.con.execute("SELECT id, status FROM listing WHERE id IN (?,?)", (a, b)).fetchall())
        self.assertEqual(st, {a: "gone", b: "active"})
        with self.assertRaises(KeyError):
            track.touch_search(self.con, "nope", "2026-01-01")


if __name__ == "__main__":
    unittest.main()
