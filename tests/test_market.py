import math
import random
import unittest

from vnrealty.listings.ingest import ingest
from vnrealty.market import index, landscape, rent
from vnrealty.store.db import connect
from vnrealty.types import Insufficient, ListingObs

WARDS = ["ngu-hanh-son", "hai-chau", "son-tra"]
WARD_LEVEL = {"ngu-hanh-son": 60e6, "hai-chau": 120e6, "son-tra": 80e6}


def synth(con, months=6, per_ward=8, growth=0.01, seed=3):
    """Houses re-observed monthly with asking/m² = ward level × (1+growth)^month × lot noise. Plus some rentals."""
    rng = random.Random(seed)
    obs = []
    sid = 0
    for w in WARDS:
        for k in range(per_ward):
            sid += 1
            area = rng.choice([60.0, 80.0, 100.0, 120.0])
            addr = "Đường Lê " + "".join(chr(97 + int(d)) for d in str(sid)) + "x"
            noise = math.exp(rng.gauss(0, 0.05))
            for m in range(months):
                ppm2 = WARD_LEVEL[w] * (1 + growth) ** m * noise
                obs.append(ListingObs(site="batdongsan", site_id=str(sid), seen_at=f"2026-{m + 1:02d}-15",
                                      ptype="house", price=round(ppm2 * area), area_m2=area, ward_code=w,
                                      address=addr))
            # the same property on a second site at a different price, seen once
            obs.append(ListingObs(site="chotot", site_id=f"c{sid}", seen_at="2026-03-20", ptype="house",
                                  price=round(WARD_LEVEL[w] * 1.1 * area * noise), area_m2=area, ward_code=w,
                                  address=addr))
        for k in range(6):
            sid += 1
            obs.append(ListingObs(site="chotot", site_id=f"r{sid}", seen_at=f"2026-{months:02d}-10", kind="rent",
                                  ptype="house", price=WARD_LEVEL[w] * 100 * 0.004, area_m2=100.0, ward_code=w))
    ingest(con, obs)


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.con = connect(":memory:")
        self.addCleanup(self.con.close)
        synth(self.con)

    def test_ppm2_table(self):
        t = index.ppm2_table(self.con, "2026-06-30", min_n=5)
        jan = [r for r in t if r["month"] == "2026-01" and r["ward_code"] == "hai-chau"][0]
        self.assertEqual(jan["n"], 8)
        self.assertAlmostEqual(jan["median"] / 120e6, 1.0, delta=0.05)
        self.assertLessEqual(jan["q1"], jan["median"])
        thin = index.ppm2_table(self.con, "2026-06-30", min_n=20)
        self.assertTrue(all(r["insufficient"] and r["median"] is None for r in thin))
        # point in time: nothing after as_of
        self.assertEqual({r["month"] for r in index.ppm2_table(self.con, "2026-02-28")}, {"2026-01", "2026-02"})

    def test_one_obs_per_listing_month(self):
        rows = index.monthly_obs(self.con, "2026-03-31", ward_code="son-tra")
        keys = [(r["listing_id"], r["month"]) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_repeat_index(self):
        r = index.repeat_index(self.con, "2026-06-30")
        idx = {m["month"]: m["index"] for m in r["months"]}
        self.assertAlmostEqual(idx["2026-06"], 100 * 1.01 ** 5, places=1)
        thin = index.repeat_index(self.con, "2026-06-30", min_pairs=100)
        self.assertIsInstance(thin, Insufficient)
        self.assertIsInstance(index.repeat_index(self.con, "2026-01-31"), Insufficient)

    def test_hedonic_index(self):
        h = index.hedonic_index(self.con, "2026-06-30", min_n=30)
        idx = {m["month"]: m["index"] for m in h["months"]}
        self.assertAlmostEqual(idx["2026-06"] / 100, 1.01 ** 5, delta=0.02)
        self.assertGreater(h["r2"], 0.8)
        self.assertIsInstance(index.hedonic_index(self.con, "2026-06-30", min_n=10_000), Insufficient)


class TestLandscape(unittest.TestCase):
    def setUp(self):
        self.con = connect(":memory:")
        self.addCleanup(self.con.close)
        synth(self.con)

    def test_supply_flow(self):
        s = landscape.supply(self.con, "2026-06-30")
        self.assertEqual(s["n"], 24)                       # the 24 sale houses seen in June (cross-site copies merged)
        f = landscape.flow(self.con, "2026-06-30", months=6)
        self.assertEqual(f[0]["new"], 24)
        self.assertIsNone(f[-1]["gone"])                   # June's gone count is not decidable on June 30
        f2 = landscape.flow(self.con, "2026-09-30", months=9)
        self.assertEqual([r for r in f2 if r["month"] == "2026-06"][0]["gone"], 24)

    def test_dom_cuts_dispersion(self):
        self.assertIsInstance(landscape.days_on_market(self.con, "2026-06-30"), Insufficient)  # all still active
        d = landscape.days_on_market(self.con, "2026-09-30")
        self.assertEqual(d["n_completed"], 24)
        self.assertEqual(d["median_completed"], 151)
        c = landscape.price_cuts(self.con, "2026-06-30")
        self.assertEqual((c["n_cut"], c["cut_rate"]), (0, 0.0))  # prices only rise; the chotot copy is not a cut
        disp = landscape.dispersion(self.con, "2026-06-30", ward_code="hai-chau")
        self.assertLess(disp["iqr_ratio"], 0.3)

    def test_summary_notes_from_numbers(self):
        s = landscape.summary(self.con, "2026-06-30", "hai-chau", "house")
        self.assertEqual(s["supply"]["n"], 8)
        self.assertTrue(any("8 active" in n for n in s["notes"]))
        self.assertTrue(any(n.startswith("days on market: insufficient") for n in s["notes"]))
        self.assertIn("insufficient", s["days_on_market"])


class TestRent(unittest.TestCase):
    def setUp(self):
        self.con = connect(":memory:")
        self.addCleanup(self.con.close)
        synth(self.con)

    def test_rent_and_yield(self):
        r = rent.rent_ppm2(self.con, "son-tra", "house", "2026-06-30")
        self.assertAlmostEqual(r["median"], 80e6 * 0.004)
        y = rent.gross_yield(self.con, "son-tra", "house", "2026-06-30")
        self.assertEqual((y["n_rent"], y["n_sale"]), (6, 8))
        self.assertAlmostEqual(y["yield"], 12 * 0.004 / 1.01 ** 5, delta=0.004)
        self.assertEqual(y["method"], "asking_gross_yield")
        thin = rent.gross_yield(self.con, "son-tra", "house", "2026-06-30", min_n=7)
        self.assertIsInstance(thin, Insufficient)
        self.assertIsInstance(rent.gross_yield(self.con, "son-tra", "house", "2026-05-31"), Insufficient)  # PIT: no rents yet
        self.assertIn("yield", rent.gross_yield(self.con, "son-tra", "house", "2026-06-30", basis="total"))
        with self.assertRaises(ValueError):
            rent.gross_yield(self.con, "son-tra", "house", basis="x")


if __name__ == "__main__":
    unittest.main()
