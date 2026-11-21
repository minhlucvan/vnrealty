import json
import tempfile
import unittest

from vnrealty.types import Insufficient
from vnrealty.valuation.official import fold, load_table, lookup


class TestOfficial(unittest.TestCase):
    def test_every_row_cited(self):
        doc = load_table()
        self.assertTrue(doc["decision"]["number"])
        for r in doc["rows"]:
            self.assertIn(r["source"], doc["sources"])
            self.assertTrue(doc["sources"][r["source"]]["url"].startswith("https://"))
            self.assertGreater(r["price_m2"], 1e6)

    def test_lookup_diacritics_insensitive(self):
        self.assertEqual(lookup("bach dang"), 340970000.0)
        self.assertEqual(lookup("Bạch Đằng", 1), 340970000.0)

    def test_ambiguous_street_needs_area(self):
        r = lookup("Trần Phú")
        self.assertIsInstance(r, Insufficient)
        self.assertEqual(len(r.detail["segments"]), 2)
        self.assertEqual(lookup("Trần Phú", area="Hội An"), 170670000.0)

    def test_unsourced_position_and_street(self):
        self.assertIsInstance(lookup("Bạch Đằng", 3), Insufficient)
        self.assertIsInstance(lookup("Phố Không Có"), Insufficient)

    def test_custom_table(self):
        doc = {"decision": {"number": "X"}, "rows": [{"street": "A", "segment": "s", "area": "z", "position": 2,
                                                      "price_m2": 5}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(doc, fh)
        self.assertEqual(lookup("a", 2, path=fh.name), 5.0)

    def test_fold(self):
        self.assertEqual(fold("  Đường  Võ Chí Công "), "duong vo chi cong")


if __name__ == "__main__":
    unittest.main()
