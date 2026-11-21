import json
import unittest

from tests.valuation_fixtures import close_all, add_listing, add_sale, db
from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation.calibrate import record, score
from vnrealty.valuation.comps import load_params


class TestCalibrate(unittest.TestCase):
    def test_record_estimate_and_insufficient(self):
        con = db()
        i = record(con, "lot:x", Estimate("comps", 1e9, 9e8, 1.1e9, n=5, as_of="2026-11-01"))
        j = record(con, "lot:x", Insufficient("hedonic", "thin"), as_of="2026-11-01")
        rows = {r["id"]: dict(r) for r in con.execute("SELECT * FROM valuation")}
        self.assertEqual(rows[i]["value"], 1e9)
        self.assertIsNone(rows[j]["value"])
        self.assertEqual(json.loads(rows[j]["inputs"])["insufficient"], "thin")

    def test_score_sale_first_then_haircut_asking(self):
        con = db()
        a = add_listing(con, obs=[("2026-01-01", 1.2e9, "asking")])
        add_sale(con, listing_id=a, sold_at="2026-05-01", price=1.0e9)
        b = add_listing(con, obs=[("2026-01-01", 1.0e9, "asking"), ("2026-06-01", 1.0e9, "asking")])
        record(con, f"listing:{a}", Estimate("comps", 1.1e9, 0.95e9, 1.2e9, as_of="2026-02-01"))
        record(con, f"listing:{b}", Estimate("comps", 0.9e9, 0.8e9, 0.95e9, as_of="2026-02-01"))
        s = score(con, "2026-11-01")["comps"]
        hc = load_params()["asking_to_sale"]["value"]
        self.assertEqual((s["n"], s["n_sale"], s["n_asking"]), (2, 1, 1))
        self.assertAlmostEqual(s["mape_sale"], 0.1)
        self.assertAlmostEqual(s["mape"], (0.1 + abs(0.9e9 - 1e9 * hc) / (1e9 * hc)) / 2)
        self.assertEqual(s["coverage"], 1.0)
        self.assertEqual(s["n_eff"], 1.5)

    def test_score_is_point_in_time(self):
        con = db()
        a = add_listing(con, obs=[("2026-01-01", 1.2e9, "asking")])
        add_sale(con, listing_id=a, sold_at="2026-12-01", price=1.0e9)
        record(con, f"listing:{a}", Estimate("comps", 1.1e9, 1e9, 1.2e9, as_of="2026-02-01"))
        self.assertEqual(score(con, "2026-11-01"), {})          # truth not yet visible; earlier asking is not later
        self.assertEqual(score(con, "2027-01-01")["comps"]["n_sale"], 1)

    def test_unit_subject_resolves_through_listing(self):
        con = db()
        a = add_listing(con, obs=[("2026-01-01", 1e9, "asking")])
        con.execute("INSERT INTO unit(id, name, listing_id) VALUES ('u1', 'test unit', ?)", (a,))
        add_sale(con, listing_id=a, sold_at="2026-04-01", price=1e9)
        record(con, "unit:u1", Estimate("index_moved", 1e9, 0.9e9, 1.1e9, as_of="2026-02-01"))
        self.assertEqual(score(con, "2026-11-01")["index_moved"]["mape"], 0.0)


def tearDownModule():
    close_all()


if __name__ == "__main__":
    unittest.main()
