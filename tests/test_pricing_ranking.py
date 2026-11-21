"""Ranking fixes: confidence-shrunk rank score, within-type ranks, estimated floor area, building-cost ratio."""
import unittest

from vnrealty.pricing.screen import rank_score
from vnrealty.pricing.zoning import floor_area


class TestRankScore(unittest.TestCase):
    def test_thin_evidence_is_pulled_to_neutral(self):
        self.assertEqual(rank_score(100, 0.5), 75)
        self.assertAlmostEqual(rank_score(70, 0.95), 69)
        self.assertGreater(rank_score(80, 1.0), rank_score(100, 0.5))
        self.assertIsNone(rank_score(None, 0.9))

    def test_bad_score_on_thin_evidence_is_also_pulled_up_to_neutral(self):
        self.assertEqual(rank_score(0, 0.5), 25)


class TestFloorArea(unittest.TestCase):
    def test_stated_floor_area_wins(self):
        self.assertEqual(floor_area({"ptype": "house", "floor_area_m2": 250, "area_m2": 80, "floors": 4}), (250.0, False))

    def test_estimate_uses_coverage(self):
        fa, est = floor_area({"ptype": "house", "area_m2": 100, "floors": 3})
        self.assertTrue(est)
        self.assertAlmostEqual(fa, 100 * 3 * 0.9)   # QCVN: a 100 m² lot may cover 90%

    def test_unknown_floors_is_none(self):
        self.assertIsNone(floor_area({"ptype": "house", "area_m2": 100}))

    def test_apartment_uses_its_own_area(self):
        self.assertEqual(floor_area({"ptype": "apartment", "area_m2": 68}), (68.0, False))


class TestScreenByType(unittest.TestCase):
    def test_by_type_ranks_within_type(self):
        from tests import pricing_fixtures as F
        from vnrealty.pricing import screen
        con = F.db()
        F.spread(con, 12, ptype="land", lo=40e6, hi=60e6)
        F.spread(con, 12, ptype="house", lo=60e6, hi=90e6, floor_area=270)
        r = screen.rank_listings(con, "2026-11-01", top=5, ctx_overrides={"hedonic": False})
        self.assertIn("land", r["by_type"])
        for t, rows in r["by_type"].items():
            self.assertEqual([x["type_rank"] for x in rows], list(range(1, len(rows) + 1)))
            self.assertTrue(all(x["ptype"] == t for x in rows))
            rs = [x["rank_score"] for x in rows]
            self.assertEqual(rs, sorted(rs, reverse=True))
        F.close_all()


if __name__ == "__main__":
    unittest.main()
