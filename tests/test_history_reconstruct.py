import unittest

from vnrealty.history.reconstruct import index_at, reconstruct
from vnrealty.types import Insufficient

IDX = [(f"{y}-{m:02d}", 40.0 + (y - 2019) * 6 + m * 0.5) for y in range(2019, 2027) for m in range(1, 13)]


class TestReconstruct(unittest.TestCase):
    def test_single_fact_moves_with_index(self):
        out = reconstruct([("2024-03", 2.2e9, "fact")], IDX, list(range(2020, 2027)))
        by = {r["year"]: r for r in out}
        self.assertEqual(by[2024]["label"], "fact")
        self.assertEqual(by[2024]["value"], 2.2e9)
        self.assertEqual(by[2024]["lo"], by[2024]["hi"])
        self.assertEqual(by[2022]["label"], "reconstructed")
        self.assertLess(by[2022]["value"], 2.2e9)
        # wider further from the anchor
        w = lambda r: r["hi"] / r["value"] - 1
        self.assertGreater(w(by[2020]), w(by[2022]))

    def test_path_passes_through_each_fact(self):
        anchors = [("2020-07", 1.0e9, "fact"), ("2024-07", 2.5e9, "fact")]
        out = reconstruct(anchors, IDX, [2020, 2022, 2024])
        self.assertEqual(out[0]["value"], 1.0e9)
        self.assertEqual(out[2]["value"], 2.5e9)
        r20 = 1.0e9 / index_at(IDX, 2020 + 6.5 / 12)
        r24 = 2.5e9 / index_at(IDX, 2024 + 6.5 / 12)
        mid = out[1]["value"] / index_at(IDX, 2022.5)
        self.assertTrue(min(r20, r24) < mid < max(r20, r24))

    def test_estimate_anchor_has_base_band(self):
        out = reconstruct([("2023-07", 1e9, "estimate")], IDX, [2023], estimate_band=0.1, band_per_year=0.05)
        self.assertEqual(out[0]["label"], "reconstructed")
        self.assertAlmostEqual(out[0]["hi"] / out[0]["value"] - 1, 0.1, delta=0.005)

    def test_uncovered_year_announces_itself(self):
        out = reconstruct([("2024-03", 2.2e9, "fact")], IDX, [2015, 2024])
        self.assertIsNone(out[0]["value"])
        self.assertEqual(out[0]["label"], "insufficient")

    def test_insufficient(self):
        self.assertIsInstance(reconstruct([], IDX, [2024]), Insufficient)
        self.assertIsInstance(reconstruct([("2010-01", 1e9, "fact")], IDX, [2024]), Insufficient)
        with self.assertRaises(ValueError):
            reconstruct([("2024-01", 1e9, "guess")], IDX, [2024])


if __name__ == "__main__":
    unittest.main()
