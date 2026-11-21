import unittest

from tests.valuation_fixtures import close_all, add_listing, add_sale, db
from vnrealty.types import Comp, Estimate, Insufficient
from vnrealty.valuation.comps import (adjust, alley_factor, haversine_km, load_params, months_back, select_comps,
                                      value_by_comps)

SUBJ = {"ptype": "land", "ward_code": "w-a", "lat": 16.0, "lng": 108.2, "area_m2": 100.0, "frontage_m": 5.0,
        "alley_m": 4.0, "corner": False, "legal": "so_hong"}


def comp(**attrs):
    a = {"corner": 0, "alley_m": 4.0, "frontage_m": 5.0, "legal": "so_hong", "area_m2": 100.0}
    a.update(attrs)
    return Comp(listing_id=1, price=5e9, area_m2=a["area_m2"], price_m2=5e9 / a["area_m2"], adj_price_m2=5e9 / a["area_m2"],
                kind="asking", seen_at="2026-10-01", adjustments={"attrs": a})


class TestHelpers(unittest.TestCase):
    def test_haversine(self):
        self.assertAlmostEqual(haversine_km(16, 108, 16, 108), 0.0)
        self.assertAlmostEqual(haversine_km(16, 108, 16.01, 108), 1.112, places=2)

    def test_months_back(self):
        self.assertEqual(months_back("2026-03-31", 1), "2026-02-28")
        self.assertEqual(months_back("2026-11-21", 12), "2025-11-21")

    def test_alley_curve(self):
        pts = load_params()["alley_curve"]["points"]
        self.assertEqual(alley_factor(0, pts), 1.0)
        self.assertAlmostEqual(alley_factor(3.75, pts), 0.55)
        self.assertEqual(alley_factor(20, pts), pts[-1][1])

    def test_params_have_basis(self):
        for k, v in load_params().items():
            self.assertIn("basis", v, k)


class TestAdjust(unittest.TestCase):
    def setUp(self):
        self.p = load_params()

    def test_identical_is_unadjusted(self):
        c = adjust(comp(), SUBJ, self.p)
        self.assertAlmostEqual(c.adj_price_m2, c.price_m2)

    def test_corner_comp_is_marked_down(self):
        c = adjust(comp(corner=1), SUBJ, self.p)
        self.assertAlmostEqual(c.adj_price_m2, c.price_m2 / (1 + self.p["corner_premium"]["value"]))

    def test_street_comp_marked_down_for_alley_subject(self):
        c = adjust(comp(alley_m=0), SUBJ, self.p)
        self.assertLess(c.adj_price_m2, c.price_m2 * 0.7)

    def test_giay_tay_subject_discounted(self):
        c = adjust(comp(), dict(SUBJ, legal="giay_tay"), self.p)
        self.assertAlmostEqual(c.adj_price_m2 / c.price_m2, self.p["legal"]["factors"]["giay_tay"])

    def test_unknown_is_recorded_not_guessed(self):
        c = adjust(comp(corner=None, legal="unknown"), SUBJ, self.p)
        self.assertEqual(c.adjustments["factors"]["corner"], "unknown")
        self.assertEqual(c.adjustments["factors"]["legal"], "unknown")
        self.assertAlmostEqual(c.adj_price_m2, c.price_m2)

    def test_size_and_frontage(self):
        c = adjust(comp(area_m2=120.0, frontage_m=7.0), SUBJ, self.p)
        f = c.adjustments["factors"]
        self.assertGreater(f["size"], 1.0)        # smaller subject asks more per m²
        self.assertLess(f["frontage"], 1.0)       # comp has wider frontage


class TestSelectAndValue(unittest.TestCase):
    def setUp(self):
        self.con = db()
        for i in range(6):
            add_listing(self.con, area=100 + i, obs=[("2026-05-01", 4e9, "asking"), ("2026-10-01", 5e9 + i * 1e8, "asking")])

    def test_latest_obs_point_in_time(self):
        early = select_comps(self.con, SUBJ, "2026-06-30")
        late = select_comps(self.con, SUBJ, "2026-11-01")
        self.assertTrue(all(c.price == 4e9 for c in early))
        self.assertTrue(all(c.price >= 5e9 for c in late))

    def test_future_obs_invisible(self):
        self.assertEqual(select_comps(self.con, SUBJ, "2026-04-30"), [])

    def test_filters(self):
        add_listing(self.con, ward="w-b", obs=[("2026-10-01", 9e9, "asking")])
        add_listing(self.con, area=300, obs=[("2026-10-01", 9e9, "asking")])
        add_listing(self.con, ptype="house", obs=[("2026-10-01", 9e9, "asking")])
        add_listing(self.con, obs=[("2026-10-01", None, "asking")])
        self.assertEqual(len(select_comps(self.con, SUBJ, "2026-11-01")), 6)

    def test_sale_supersedes_asking(self):
        lid = add_listing(self.con, obs=[("2026-09-01", 6e9, "asking")])
        add_sale(self.con, listing_id=lid, sold_at="2026-10-15", price=5.5e9)
        cs = select_comps(self.con, SUBJ, "2026-11-01")
        mine = [c for c in cs if c.listing_id == lid]
        self.assertEqual([c.kind for c in mine], ["sale"])

    def test_radius(self):
        con = db()
        add_listing(con, lat=16.0, lng=108.2, ward="w-b", obs=[("2026-10-01", 5e9, "asking")])
        add_listing(con, lat=16.2, lng=108.2, obs=[("2026-10-01", 5e9, "asking")])
        cs = select_comps(con, SUBJ, "2026-11-01", radius_km=2)
        self.assertEqual(len(cs), 1)
        self.assertLess(cs[0].distance_km, 0.01)

    def test_value_applies_haircut_explicitly(self):
        e = value_by_comps(self.con, SUBJ, "2026-11-01")
        self.assertIsInstance(e, Estimate)
        hc = load_params()["asking_to_sale"]
        self.assertEqual(e.detail["haircut"]["value"], hc["value"])
        self.assertEqual(e.detail["n_asking"], 6)
        raw_median = sorted((5e9 + i * 1e8) / (100 + i) for i in range(6))
        self.assertLess(e.value, (raw_median[2] + raw_median[3]) / 2 * 100)
        self.assertLessEqual(e.lo, e.value)
        self.assertGreaterEqual(e.hi, e.value)

    def test_insufficient_below_five(self):
        con = db()
        for i in range(4):
            add_listing(con, obs=[("2026-10-01", 5e9, "asking")])
        r = value_by_comps(con, SUBJ, "2026-11-01")
        self.assertIsInstance(r, Insufficient)
        self.assertIn("4 comparables", r.reason)

    def test_subject_without_area(self):
        self.assertIsInstance(value_by_comps(self.con, dict(SUBJ, area_m2=None), "2026-11-01"), Insufficient)


def tearDownModule():
    close_all()


if __name__ == "__main__":
    unittest.main()


class TestSelfExclusion(unittest.TestCase):
    def test_listing_is_not_its_own_comp(self):
        from vnrealty.store.db import connect
        from vnrealty.valuation.comps import select_comps
        con = connect(":memory:")
        con.execute("INSERT INTO ward(code, name_vi) VALUES ('w', 'W')")
        for i in range(1, 4):
            con.execute("INSERT INTO listing(id, fingerprint, ptype, ward_code, area_m2, first_seen, last_seen) VALUES (?, ?, 'land', 'w', 100, '2026-10-01', '2026-11-01')", (i, f"f{i}"))
            con.execute("INSERT INTO listing_obs(listing_id, seen_at, site, kind, price, price_m2) VALUES (?, '2026-11-01', 's', 'asking', ?, ?)", (i, 3e9 + i, (3e9 + i) / 100))
        subj = {"ptype": "land", "ward_code": "w", "area_m2": 100, "listing_id": 2}
        ids = {c.listing_id for c in select_comps(con, subj, "2026-11-21")}
        self.assertNotIn(2, ids)
        self.assertEqual(ids, {1, 3})
        con.close()
