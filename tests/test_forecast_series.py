import math
import unittest

from vnrealty.forecast import series as S
from vnrealty.store.db import connect
from vnrealty.types import Insufficient


class TestMonths(unittest.TestCase):
    def test_norm_month(self):
        for raw, want in [("2025-03", "2025-03"), ("2025-03-15T00:00", "2025-03"), ("03/2025", "2025-03"),
                          ("T3/2025", "2025-03"), ("Tháng 3/2025", "2025-03"), ("Q1/2025", "2025-02"),
                          ("Quý 4 2024", "2024-11"), ("15/03/2025", "2025-03"), (1740787200000, "2025-03"),
                          ("hello", None), (None, None), (12, None)]:
            self.assertEqual(S.norm_month(raw), want, raw)

    def test_month_arith(self):
        self.assertEqual(S.month_add("2025-11", 3), "2026-02")
        self.assertEqual(S.month_add("2025-01", -1), "2024-12")
        self.assertEqual(S.month_diff("2024-12", "2026-02"), 14)

    def test_parse_unit(self):
        self.assertEqual(S.parse_unit("triệu/m²"), ("vnd_m2", 1e6))
        self.assertEqual(S.parse_unit("Tỷ"), ("vnd", 1e9))
        self.assertEqual(S.parse_unit("đ/m2"), ("vnd_m2", 1.0))
        self.assertIsNone(S.parse_unit("bananas"))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.con = connect(":memory:")

    def test_pit_latest_vintage(self):
        S.add_points(self.con, "bds-chart", "ward", "hoa-quy", "land", [("2025-01", 30e6), ("2025-02", 31e6)],
                     "vnd_m2", "https://x/1", "2025-03-01")
        S.add_points(self.con, "bds-chart", "ward", "hoa-quy", "land", [("2025-02", 32e6), ("2025-03", 33e6)],
                     "vnd_m2", "https://x/1", "2025-04-01")
        early = S.get_series(self.con, "ward", "hoa-quy", "land", as_of="2025-03-15")["bds-chart"]
        self.assertEqual(early.points, [("2025-01", 30e6), ("2025-02", 31e6)])
        late = S.get_series(self.con, "ward", "hoa-quy", "land")["bds-chart"]
        self.assertEqual(dict(late.points)["2025-02"], 32e6)       # revised vintage wins
        self.assertEqual(late.vintages["2025-02"], "2025-04-01")
        # months after as_of are never returned even if seen earlier
        S.add_points(self.con, "x", "ward", "hoa-quy", "land", [("2025-09", 1.0)], "vnd_m2", None, "2025-01-01")
        self.assertNotIn("x", S.get_series(self.con, "ward", "hoa-quy", "land", as_of="2025-05-01"))

    def test_bad_point_raises_and_dupe_noop(self):
        with self.assertRaises(ValueError):
            S.add_points(self.con, "s", "city", "da-nang", None, [("nope", 1)], "vnd_m2", None, "2025-01-01")
        self.assertEqual(S.add_points(self.con, "s", "city", "da-nang", None, [("2025-01", 1)], "index", None,
                                      "2025-02-01"), 1)
        self.assertEqual(S.add_points(self.con, "s", "city", "da-nang", None, [("2025-01", 1)], "index", None,
                                      "2025-02-01"), 0)
        self.assertIn("s", S.get_series(self.con, "city", "da-nang", None))


class TestSplice(unittest.TestCase):
    def mk(self, src, pts, unit="vnd_m2"):
        return S.Series(src, "ward", "w", "land", "asking", unit, pts)

    def test_chain_link_by_overlap(self):
        old = self.mk("dkra", [(f"2024-{m:02d}", 10.0 * (1 + 0.01 * m)) for m in range(1, 9)], "index")
        new = self.mk("bds", [(f"2024-{m:02d}", 3e6 * (1 + 0.01 * m)) for m in range(5, 13)])
        r = S.splice([old, new])
        self.assertEqual(r["base"], "bds")
        self.assertEqual(r["links"][0]["overlap_months"], 4)
        self.assertAlmostEqual(r["links"][0]["ratio"], 3e5, places=3)
        self.assertAlmostEqual(dict(r["points"])["2024-01"], 3e6 * 1.01, places=3)
        self.assertEqual(len(r["points"]), 12)

    def test_no_overlap_kept_separate(self):
        a = self.mk("a", [("2020-01", 1.0), ("2020-02", 1.0)])
        b = self.mk("b", [("2024-01", 2.0), ("2024-02", 2.0)])
        r = S.splice([a, b])
        self.assertEqual(len(r["points"]), 2)
        self.assertEqual(r["separate"][0]["source"], "a")
        self.assertEqual(r["links"], [])


class TestCaptureAndShape(unittest.TestCase):
    CAP = {"site": "batdongsan", "url": "https://batdongsan.com.vn/gia-dat", "seen_at": "2026-11-21T08:00:00Z",
           "kind": "series", "warnings": [],
           "items": [{"scope_text": "Ngũ Hành Sơn", "ptype_text": "Đất nền", "unit_text": "triệu/m²",
                      "points": [["2026-01", 41.5], ["T2/2026", "42,3"], ["bad", 1], ["2026-03", None]]}]}

    def test_from_capture_and_ingest(self):
        rows = S.from_capture(self.CAP)
        self.assertEqual(rows[0]["points"], [("2026-01", 41.5), ("2026-02", 42.3)])
        self.assertEqual(len(rows[0]["skipped"]), 2)
        self.assertEqual(rows[0]["unit"], "vnd_m2")
        con = connect(":memory:")
        self.assertEqual(S.ingest_capture(con, self.CAP, "old_district", "ngu-hanh-son", "land"), 2)
        s = S.get_series(con, "old_district", "ngu-hanh-son", "land")["batdongsan-chart"]
        self.assertAlmostEqual(s.points[1][1], 42.3e6)
        bad = dict(self.CAP, items=[dict(self.CAP["items"][0], unit_text="??")])
        self.assertIsInstance(S.ingest_capture(con, bad, "city", "x", None), Insufficient)
        with self.assertRaises(ValueError):
            S.from_capture({"items": []})

    def test_index_and_regularize(self):
        idx = S.to_index([("2025-01", 50.0), ("2025-02", 55.0)], "2025-01")
        self.assertEqual(idx[1], ("2025-02", 110.0))
        self.assertIsInstance(S.to_index([("2025-01", 50.0)], "2024-01"), Insufficient)
        pts = [("2025-01", 100.0), ("2025-04", 100 * math.exp(0.03)), ("2026-01", 120.0), ("2026-02", 121.0)]
        r = S.regularize(pts)
        self.assertEqual(r["filled"], ["2025-02", "2025-03"])
        self.assertAlmostEqual(dict(r["points"])["2025-02"], 100 * math.exp(0.01))
        self.assertEqual(r["gaps"], [("2025-05", "2025-12")])
        self.assertEqual(S.last_segment(pts), [("2026-01", 120.0), ("2026-02", 121.0)])
        self.assertEqual(S.subject_for("bds", "ward", "hoa-quy", "land"), "series:bds:ward/hoa-quy:land")


if __name__ == "__main__":
    unittest.main()
