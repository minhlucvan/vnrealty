import math
import unittest

from tests import pricing_fixtures as F
from vnrealty.pricing import metrics as M
from vnrealty.pricing import peers, zoning
from vnrealty.types import Estimate

AS_OF = "2026-11-01"


def tearDownModule():
    F.close_all()


def ctx(con, **kw):
    return M.make_ctx(con, AS_OF, **kw)


class TestLand(unittest.TestCase):
    def setUp(self):
        self.con = F.db()
        F.spread(self.con, 10, ptype="land", area=100, lo=40e6, hi=60e6, alley=3.0)
        # houses: 30 M VND per m² of floor area
        F.spread(self.con, 10, ptype="house", area=100, lo=300e3 * 100, hi=300e3 * 100, unit="abs", floor_area=1.0)

    def test_price_metrics_and_peer(self):
        lid = F.add(self.con, area=100, obs=(("2026-10-01", 4.2e9),), alley=3.0, frontage=5.0)
        m = M.land(peers.snapshot(self.con, lid, AS_OF), ctx(self.con))
        self.assertAlmostEqual(m["price_m2"]["value"], 42e6)
        self.assertEqual(m["price_m2"]["peer"]["n"], 10)
        self.assertLess(m["price_m2"]["peer"]["percentile"], 20)
        self.assertAlmostEqual(m["gfa_m2"]["value"], 100 * 0.9 * 4)
        self.assertAlmostEqual(m["price_per_buildable_m2"]["value"], 4.2e9 / 360)
        self.assertAlmostEqual(m["price_per_frontage_m"]["value"], 4.2e9 / 5)

    def test_residual_arithmetic(self):
        # houses at exactly 30 M/m² floor: price 30e6 × floor area 100
        con = F.db()
        F.spread(con, 10, ptype="house", area=100, lo=3e9, hi=3e9, unit="abs", floor_area=100)
        lid = F.add(con, area=100, obs=(("2026-10-01", 4e9),), alley=3.0)
        c = ctx(con)
        m = M.land(peers.snapshot(con, lid, AS_OF), c)
        p = c["params"]
        gfa = 360.0
        gdv = 30e6 * gfa * 0.90
        build = gfa * p["build_cost_m2"]["standard"]
        soft = build * p["soft_cost_share"]["value"]
        fin = (build + soft) * p["finance_rate"]["value"] * (0.5 * p["build_months"]["value"] + p["sale_months"]["value"]) / 12
        resid = gdv - build - soft - p["developer_margin"]["value"] * gdv - fin
        self.assertEqual(m["gdv"]["route"], "sell_house")  # no room rent peers → only the sale route
        self.assertAlmostEqual(m["residual_value"]["value"], resid, places=0)
        self.assertAlmostEqual(m["residual_vs_asking"]["ratio"], resid / 4e9)

    def test_studio_route_when_room_rents_known(self):
        con = F.db()
        lid = F.add(con, area=100, obs=(("2026-10-01", 4e9),), alley=3.0)
        m = M.land(peers.snapshot(con, lid, AS_OF), ctx(con, studio_rent=5e6))
        units = math.floor(360 * 0.75 / 25)
        noi = units * 5e6 * 12 * 0.9 * 0.8
        self.assertEqual(m["gdv"]["route"], "build_studios")
        self.assertAlmostEqual(m["gdv"]["value"], noi / 0.08)

    def test_unknown_alley_is_insufficient_not_defaulted(self):
        lid = F.add(self.con, area=100, obs=(("2026-10-01", 4e9),), alley=None)
        m = M.land(peers.snapshot(self.con, lid, AS_OF), ctx(self.con))
        self.assertIn("insufficient", m["residual_vs_asking"])
        self.assertIn("insufficient", m["price_per_buildable_m2"])
        self.assertIn("value", m["price_m2"])

    def test_street_lot_lower_bound_and_official_ratio(self):
        lid = F.add(self.con, area=100, obs=(("2026-10-01", 30e9),), alley=0.0, street="Bạch Đằng")
        m = M.land(peers.snapshot(self.con, lid, AS_OF), ctx(self.con))
        self.assertEqual(m["gfa_m2"]["bound"], "lower")
        self.assertAlmostEqual(m["official_ratio"]["value"], 300e6 / 340970000)

    def test_no_price(self):
        lid = F.add(self.con, area=100, obs=(("2026-10-01", None),))
        m = M.land(peers.snapshot(self.con, lid, AS_OF), ctx(self.con))
        self.assertTrue(all("insufficient" in v for v in m.values()))


class TestHouse(unittest.TestCase):
    def test_cost_approach(self):
        con = F.db()
        F.spread(con, 10, ptype="land", area=100, lo=50e6, hi=50e6)  # land comps at 50 M/m²
        lid = F.add(con, ptype="house", area=100, floor_area=200, obs=(("2026-10-01", 6e9),))
        c = ctx(con, age_years=10)
        m = M.house(peers.snapshot(con, lid, AS_OF), c)
        land = 50e6 * 100 * 0.90  # comps: asking × haircut, same attributes
        self.assertAlmostEqual(m["land_value"]["value"], land, delta=land * 1e-6)
        bld = 200 * c["params"]["build_cost_m2"]["standard"] * (1 - 10 / 40)
        self.assertAlmostEqual(m["building_value"]["value"], bld)
        self.assertAlmostEqual(m["cost_value_vs_asking"]["ratio"], (land + bld) / 6e9, places=6)
        self.assertAlmostEqual(m["implied_building_value"]["value"], 6e9 - land, delta=1)

    def test_age_unknown_is_insufficient(self):
        con = F.db()
        F.spread(con, 10, ptype="land", area=100, lo=50e6, hi=50e6)
        lid = F.add(con, ptype="house", area=100, floor_area=200, obs=(("2026-10-01", 6e9),))
        m = M.house(peers.snapshot(con, lid, AS_OF), ctx(con))
        self.assertIn("age", m["building_value"]["insufficient"])
        self.assertIn("insufficient", m["cost_value_vs_asking"])
        self.assertIn("value", m["implied_building_value"])

    def test_yield_from_peers_is_not_independent(self):
        con = F.db()
        F.spread(con, 10, ptype="house", area=100, lo=200e3, hi=200e3, deal="rent")
        lid = F.add(con, ptype="house", area=100, floor_area=200, obs=(("2026-10-01", 6e9),))
        m = M.house(peers.snapshot(con, lid, AS_OF), ctx(con))
        self.assertAlmostEqual(m["gross_yield"]["value"], 20e6 * 12 / 6e9)
        self.assertFalse(m["gross_yield"]["independent"])
        self.assertIn("insufficient", m["gross_yield_vs_ward"])

    def test_yield_vs_ward_with_listing_rent(self):
        con = F.db()
        F.spread(con, 10, ptype="house", area=100, lo=200e3, hi=200e3, deal="rent")
        F.spread(con, 10, ptype="house", area=100, lo=60e6, hi=60e6)
        lid = F.add(con, ptype="house", area=100, obs=(("2026-10-01", 6e9),))
        m = M.house(peers.snapshot(con, lid, AS_OF), ctx(con, rent=30e6))
        ward = 200e3 * 12 / 60e6
        self.assertAlmostEqual(m["gross_yield_vs_ward"]["ratio"], (30e6 * 12 / 6e9) / ward)


class TestApartment(unittest.TestCase):
    def test_project_peers_and_yields(self):
        con = F.db()
        F.spread(con, 6, ptype="apartment", area=60, lo=60e6, hi=70e6, title="Căn hộ Monarchy B 2PN")
        F.spread(con, 10, ptype="apartment", area=60, lo=30e6, hi=40e6, title="Bán căn hộ giá rẻ")
        lid = F.add(con, ptype="apartment", area=60, obs=(("2026-10-01", 3.6e9),), legal="hdmb",
                    title="Bán căn hộ Monarchy B view sông")
        c = ctx(con, rent=15e6)
        m = M.apartment(peers.snapshot(con, lid, AS_OF), c)
        self.assertEqual(m["price_m2_floor"]["peer"]["scope"], "project")
        self.assertEqual(m["price_m2_floor"]["project"], "monarchy b")
        self.assertEqual(m["legal"]["value"], "hdmb")
        self.assertAlmostEqual(m["gross_yield"]["value"], 15e6 * 12 / 3.6e9)
        fee = c["params"]["apartment_mgmt_fee_m2"]["value"]
        self.assertAlmostEqual(m["net_yield"]["value"], (15e6 * 12 * 0.9 - fee * 60 * 12) / 3.6e9)
        self.assertAlmostEqual(m["price_to_rent"]["value"], 3.6e9 / (15e6 * 12))

    def test_no_rent_anywhere(self):
        con = F.db()
        lid = F.add(con, ptype="apartment", area=60, obs=(("2026-10-01", 3.6e9),))
        m = M.apartment(peers.snapshot(con, lid, AS_OF), ctx(con))
        for k in ("gross_yield", "net_yield", "price_to_rent"):
            self.assertIn("insufficient", m[k])


class TestShophouseAndRooms(unittest.TestCase):
    def test_shophouse(self):
        con = F.db()
        F.spread(con, 9, ptype="shophouse", area=100, lo=1e9, hi=2e9, unit="abs", frontage=5)
        lid = F.add(con, ptype="shophouse", area=100, frontage=6, obs=(("2026-10-01", 6e9),))
        m = M.shophouse(peers.snapshot(con, lid, AS_OF), ctx(con, rent=40e6))
        self.assertAlmostEqual(m["price_per_frontage_m"]["value"], 1e9)
        self.assertAlmostEqual(m["rent_per_frontage_m"]["value"], 40e6 / 6)
        self.assertTrue(m["gross_yield"]["independent"])

    def test_chdv_income_approach(self):
        con = F.db()
        lid = F.add(con, ptype="chdv", area=100, bedrooms=10, obs=(("2026-10-01", 10e9),), title="Bán tòa CHDV")
        c = ctx(con, room_rent=5e6)
        m = M.rooms(peers.snapshot(con, lid, AS_OF), c)
        noi = 10 * 5e6 * 12 * 0.9 * 0.75
        self.assertAlmostEqual(m["noi"]["value"], noi)
        self.assertAlmostEqual(m["income_value_vs_asking"]["ratio"], noi / 0.08 / 10e9)
        self.assertAlmostEqual(m["implied_cap_rate"]["value"], noi / 10e9)
        self.assertAlmostEqual(m["revenue_multiple"]["value"], 10e9 / (10 * 5e6 * 12 * 0.9))

    def test_homestay_needs_adr(self):
        con = F.db()
        lid = F.add(con, ptype="chdv", area=100, bedrooms=8, obs=(("2026-10-01", 10e9),), title="Bán homestay An Thượng")
        snap = peers.snapshot(con, lid, AS_OF)
        self.assertEqual(M.operating_mode(snap, {}), "homestay")
        m = M.rooms(snap, ctx(con))
        self.assertIn("ADR", m["income_value_vs_asking"]["insufficient"])
        m = M.rooms(snap, ctx(con, adr=600e3, occupancy=0.6))
        noi = 8 * 600e3 * 0.6 * 365 * 0.85 * 0.65
        self.assertAlmostEqual(m["noi"]["value"], noi)
        self.assertAlmostEqual(m["income_value_vs_asking"]["ratio"], noi / 0.10 / 10e9)

    def test_rooms_unknown(self):
        con = F.db()
        lid = F.add(con, ptype="chdv", area=100, obs=(("2026-10-01", 10e9),))
        m = M.rooms(peers.snapshot(con, lid, AS_OF), ctx(con, room_rent=5e6))
        self.assertIn("insufficient", m["price_per_room"])
        self.assertIn("room count", m["income_value_vs_asking"]["insufficient"])


class TestCommonAndDispatch(unittest.TestCase):
    def test_common_signals_and_value_gap(self):
        con = F.db()
        lid = F.add(con, obs=(("2026-03-01", 5e9), ("2026-09-01", 4.5e9)), alley=1.5)
        snap = peers.snapshot(con, lid, AS_OF)
        m = M.common(snap, ctx(con, valuation=Estimate("triangulated", 5.4e9, 5e9, 6e9, as_of=AS_OF)))
        self.assertAlmostEqual(m["value_gap"]["ratio"], 1.2)
        self.assertEqual(m["price_cuts"]["value"], 1)
        self.assertEqual(m["days_on_market"]["value"], 245)
        self.assertEqual(m["alley_m"]["value"], 1.5)
        self.assertIn("insufficient", m["hedonic_residual"])

    def test_rental_and_dispatch(self):
        con = F.db()
        F.spread(con, 9, ptype="house", area=100, lo=150e3, hi=250e3, deal="rent")
        lid = F.add(con, ptype="house", deal="rent", area=100, obs=(("2026-10-01", 15e6),))
        m = M.evaluate(peers.snapshot(con, lid, AS_OF), ctx(con))
        self.assertAlmostEqual(m["rent_m2"]["value"], 150e3)
        self.assertIn("days_on_market", m)


if __name__ == "__main__":
    unittest.main()
