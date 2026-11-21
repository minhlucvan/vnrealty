"""Paper-deal ledger and scorecard."""
import unittest

from vnrealty.portfolio.ledger import close, list_deals, open_paper_deal, scorecard
from vnrealty.store.db import connect


class Ledger(unittest.TestCase):
    def test_open_close_and_score(self):
        con = connect(":memory:")
        a = open_paper_deal(con, "listing:1", "buy", 3e9, 3.3e9, {"why": "under comps"}, "B", opened_at="2026-01-01")
        b = open_paper_deal(con, "listing:2", "pass", 2e9, 1.8e9, None, "D", opened_at="2026-01-02")
        c = open_paper_deal(con, "listing:3", "buy", 1e9, 1.2e9, opened_at="2026-01-03")
        open_paper_deal(con, "lot:x", "hold", None, None)
        close(con, a, {"realised_value": 3.15e9}, closed_at="2026-11-01")
        close(con, b, {"realised_value": 2.1e9}, closed_at="2026-11-01")   # passed, but it was worth more: a miss
        close(con, c, {"note": "no sale evidence yet"}, closed_at="2026-11-01")
        s = scorecard(con)
        self.assertEqual((s["open"], s["closed"], s["graded"], s["ungraded"]), (1, 3, 2, [c]))
        self.assertAlmostEqual(s["hit_rate"], 0.5)
        self.assertAlmostEqual(s["avg_est_gap"], (0.1 + -0.1) / 2)
        self.assertAlmostEqual(s["avg_realised_gap"], (0.05 + 0.05) / 2)
        self.assertAlmostEqual(s["avg_estimate_error"], (3.15 / 3.3 - 1 + 2.1 / 1.8 - 1) / 2)
        self.assertEqual(list_deals(con)[0]["spec"], {"why": "under comps"})

    def test_validation(self):
        con = connect(":memory:")
        with self.assertRaises(ValueError):
            open_paper_deal(con, "x", "yolo", 1, 1)
        i = open_paper_deal(con, "x", "buy", 1, 1)
        close(con, i, {"realised_value": 1})
        with self.assertRaises(KeyError):
            close(con, i, {"realised_value": 2})

    def test_empty_scorecard(self):
        s = scorecard(connect(":memory:"))
        self.assertIsNone(s["hit_rate"])


if __name__ == "__main__":
    unittest.main()
