import unittest
from unittest import mock

from tests import pricing_fixtures as F
from vnrealty.pricing import screen

AS_OF = "2026-11-01"


def tearDownModule():
    F.close_all()


def market():
    con = F.db()
    F.spread(con, 12, ptype="land", area=100, lo=40e6, hi=62e6, alley=3.0)
    F.spread(con, 10, ptype="house", area=100, lo=3e9, hi=3e9, unit="abs", floor_area=100)
    cheap = F.add(con, area=100, obs=(("2026-10-01", 3.0e9),), alley=3.0, frontage=5.0)
    dear = F.add(con, area=100, obs=(("2026-10-01", 9.0e9),), alley=3.0, frontage=5.0)
    gone = F.add(con, area=100, obs=(("2026-03-01", 2.0e9),), alley=3.0, status="gone")
    future = F.add(con, area=100, obs=(("2026-12-01", 1.0e9),), alley=3.0)
    return con, cheap, dear, gone, future


class TestScreen(unittest.TestCase):
    def test_active_ids_point_in_time(self):
        con, cheap, dear, gone, future = market()
        ids = screen.active_ids(con, AS_OF)
        self.assertIn(cheap, ids)
        self.assertNotIn(gone, ids)
        self.assertNotIn(future, ids)

    def test_ranking_and_filters(self):
        con, cheap, dear, *_ = market()
        r = screen.rank_listings(con, AS_OF, filters={"ptypes": ["land"]}, top=50, ctx_overrides={"hedonic": False})
        ids = [row["id"] for row in r["rows"]]
        self.assertEqual(ids[0], cheap)
        self.assertGreater(r["rows"][0]["score"], 80)
        self.assertLess(ids.index(cheap), ids.index(dear))
        self.assertTrue(all(row["ptype"] == "land" for row in r["rows"]))
        self.assertEqual(r["rows"][0]["key_metric"]["name"], "price_m2")
        r2 = screen.rank_listings(con, AS_OF, filters={"ptypes": ["land"], "max_price": 3.5e9}, top=3,
                                  ctx_overrides={"hedonic": False})
        self.assertLessEqual(len(r2["rows"]), 3)
        self.assertTrue(all(row["price"] <= 3.5e9 for row in r2["rows"]))

    def test_stored_valuation_feeds_value_gap(self):
        con, cheap, *_ = market()
        con.execute("INSERT INTO valuation(subject, as_of, method, value, lo, hi, n, created_at) VALUES "
                    "(?, '2026-10-15', 'triangulated', 4.5e9, 4e9, 5e9, 9, '2026-10-15')", (f"listing:{cheap}",))
        con.execute("INSERT INTO valuation(subject, as_of, method, value, lo, hi, n, created_at) VALUES "
                    "(?, '2026-12-15', 'triangulated', 1e9, 1e9, 1e9, 9, '2026-12-15')", (f"listing:{cheap}",))
        v = screen.stored_valuation(con, cheap, AS_OF)
        self.assertEqual(v.value, 4.5e9)

    def test_strategy_layer_absent_is_reported(self):
        con, cheap, *_ = market()
        real_import = __import__

        def fake(name, *a, **k):
            if name.startswith("vnrealty.strategy"):
                raise ImportError("absent")
            return real_import(name, *a, **k)
        with mock.patch("builtins.__import__", side_effect=fake):
            r = screen.rank_listings(con, AS_OF, top=3, ctx_overrides={"hedonic": False})
        self.assertEqual(r["strategy_layer"], "strategy layer not available")
        self.assertTrue(all(row["strategy_note"] == "strategy layer not available" for row in r["rows"]))

    def test_strategy_needs_market_value(self):
        con, cheap, *_ = market()
        bs = screen.best_strategy({"price": 3e9, "area_m2": 100, "ptype": "land"}, None, None)
        if bs["available"]:
            self.assertIsNone(bs["strategy"])
            self.assertIn("market value", bs["reason"])

    def test_strategy_ranked_with_value_and_assumptions(self):
        from vnrealty.types import Estimate
        bs = screen.best_strategy({"price": 3e9, "area_m2": 100, "ptype": "land"},
                                  Estimate("triangulated", 3.3e9, 3e9, 3.6e9),
                                  {"price_growth": 0.05, "hurdle": 0.1, "hold_years": 5})
        if bs["available"]:
            self.assertEqual(bs["strategy"], "land_bank")
            self.assertIn("killed", bs["reason"])


if __name__ == "__main__":
    unittest.main()
