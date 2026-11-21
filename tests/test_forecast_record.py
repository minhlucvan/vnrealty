import unittest

from tests.forecast_fixtures import walk
from vnrealty.forecast import record as R
from vnrealty.forecast.backtest import ensemble_weights
from vnrealty.forecast.series import add_points, subject_for
from vnrealty.store.db import connect


FAN = {"months": ["2026-01", "2026-02"], "horizons": [1, 2], "p10": [90.0, 88.0], "p50": [100.0, 100.0],
       "p90": [110.0, 112.0]}


class TestRecordGrade(unittest.TestCase):
    def setUp(self):
        self.con = connect(":memory:")

    def test_series_subject(self):
        subj = subject_for("bds-chart", "ward", "hoa-quy", "land")
        self.assertEqual(R.parse_subject(subj)["scope"], "hoa-quy")
        ids = R.record(self.con, subj, "2025-12-31", "ensemble", FAN)
        self.assertEqual(len(ids), 2)
        add_points(self.con, "bds-chart", "ward", "hoa-quy", "land", [("2026-01", 105.0)], "vnd_m2", None,
                   "2026-02-05")
        g = R.grade(self.con, "2026-01-31")                     # truth not yet seen at as_of
        self.assertEqual(g["models"], {})
        g = R.grade(self.con, "2026-02-28")
        m = g["models"]["ensemble"][1]
        self.assertEqual(m["n"], 1)
        self.assertLess(m["bias"], 0)                          # under-forecast
        self.assertEqual(m["coverage"], 1.0)
        self.assertEqual(g["n_ungraded"], 1)                   # 2026-02 has no truth yet
        self.assertEqual(ensemble_weights(g, 1), {"ensemble": 1.0})

    def test_asset_subject_strengths(self):
        self.con.execute("INSERT INTO listing(id, fingerprint, ptype, first_seen, last_seen) VALUES (1,'f','land',"
                         "'2025-01-01','2026-03-01')")
        R.record(self.con, "listing:1", "2025-12-31", "asset", FAN)
        self.con.execute("INSERT INTO listing_obs(listing_id, seen_at, site, kind, price) VALUES "
                         "(1,'2026-01-20','bds','asking',120.0)")
        self.con.commit()
        g = R.grade(self.con, "2026-03-31", haircut=0.9)
        m = g["models"]["asset"]
        self.assertEqual(m[1]["by_strength"], {"asking_haircut": 1})
        self.assertEqual(m[1]["n_eff"], 0.5)
        self.con.execute("INSERT INTO valuation(subject, as_of, method, value, created_at) VALUES "
                         "('listing:1','2026-02-10','triangulated',100.0,'x')")
        self.con.execute("INSERT INTO sale_evidence(listing_id, sold_at, price, source) VALUES (1,'2026-02-15',101.0,'n')")
        self.con.commit()
        g = R.grade(self.con, "2026-03-31", haircut=0.9)
        self.assertEqual(g["models"]["asset"][1]["by_strength"], {"sale": 1})

    def test_record_skips_none(self):
        fan = dict(FAN, p50=[100.0, None])
        self.assertEqual(len(R.record(self.con, "unit:u1", "2025-12-31", "asset", fan)), 1)

    def test_grade_feeds_weights(self):
        s = walk(30, start="2024-01")
        add_points(self.con, "own", "city", "da-nang", None, s, "vnd_m2", None, "2026-07-01")
        subj = subject_for("own", "city", "da-nang", None)
        for model, bump in (("good", 1.0), ("bad", 1.3)):
            fan = {"months": [m for m, _ in s[12:]], "horizons": [3] * 18, "p10": [v * bump * 0.9 for _, v in s[12:]],
                   "p50": [v * bump for _, v in s[12:]], "p90": [v * bump * 1.1 for _, v in s[12:]]}
            R.record(self.con, subj, "2024-12-31", model, fan)
        g = R.grade(self.con, "2026-07-31")
        w = ensemble_weights(g, 3)
        self.assertGreater(w["good"], w["bad"])


if __name__ == "__main__":
    unittest.main()
