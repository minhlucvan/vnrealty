import math
import unittest

from vnrealty.types import Estimate, Insufficient
from vnrealty.valuation.index_moved import level_at, value_by_index

SERIES = [(f"2024-{m:02d}", 46.0 + m) for m in range(1, 13)] + [(f"2025-{m:02d}", 60.0 + m) for m in range(1, 13)]


class TestIndexMoved(unittest.TestCase):
    def test_moves_with_index(self):
        e = value_by_index(2.2e9, "2024-01", SERIES, "2025-12-20")
        self.assertIsInstance(e, Estimate)
        self.assertAlmostEqual(e.value / (2.2e9 * 72 / 47), 1.0)
        self.assertLess(e.lo, e.value)
        self.assertGreater(e.hi, e.value)
        self.assertAlmostEqual(math.log(e.hi / e.value), math.log(e.value / e.lo))

    def test_point_in_time_uses_latest_at_or_before(self):
        e = value_by_index(1e9, "2024-01", SERIES, "2024-06-30")
        self.assertAlmostEqual(e.value / (1e9 * 52 / 47), 1.0)
        self.assertEqual(level_at(SERIES, "2024-06"), ("2024-06", 52.0))

    def test_band_floor(self):
        flat = [(f"2024-{m:02d}", 50.0) for m in range(1, 13)]
        e = value_by_index(1e9, "2024-01", flat, "2024-12")
        self.assertAlmostEqual(e.hi / e.value, math.exp(0.05))

    def test_not_covered(self):
        self.assertIsInstance(value_by_index(1e9, "2023-06", SERIES, "2025-01"), Insufficient)
        self.assertIsInstance(value_by_index(1e9, "2024-01", SERIES, "2026-11"), Insufficient)   # lag > 6 months
        self.assertIsInstance(value_by_index(0, "2024-01", SERIES, "2025-01"), Insufficient)


if __name__ == "__main__":
    unittest.main()
