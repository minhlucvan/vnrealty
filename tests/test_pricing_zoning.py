import unittest

from vnrealty.pricing import zoning
from vnrealty.types import Insufficient


class TestZoning(unittest.TestCase):
    def test_params_carry_basis_and_sources(self):
        p = zoning.load_params()
        for name, entry in p.items():
            self.assertIn("basis", entry, name)
            self.assertIn(entry.get("basis_kind"), ("sourced", "partly_sourced", "judgement"), name)
            self.assertIn("unit", entry, name)

    def test_buildable_ratio_table_and_interpolation(self):
        self.assertEqual(zoning.buildable_ratio(80), 1.0)
        self.assertAlmostEqual(zoning.buildable_ratio(100), 0.9)
        self.assertAlmostEqual(zoning.buildable_ratio(150), 0.8)
        self.assertAlmostEqual(zoning.buildable_ratio(400), 0.55)
        self.assertEqual(zoning.buildable_ratio(5000), 0.4)
        self.assertIsInstance(zoning.buildable_ratio(None), Insufficient)

    def test_floors_by_alley_bands(self):
        self.assertEqual(zoning.floors_allowed(2.0)["floors"], 3)
        self.assertEqual(zoning.floors_allowed(2.5)["floors"], 4)
        self.assertEqual(zoning.floors_allowed(6.9)["floors"], 4)
        self.assertEqual(zoning.floors_allowed(7.0)["floors"], 5)
        self.assertEqual(zoning.floors_allowed(7.0)["max_height_m"], 20.0)

    def test_street_unknown_is_a_lower_bound_and_unknown_alley_is_insufficient(self):
        st = zoning.floors_allowed(0)
        self.assertEqual((st["floors"], st["bound"]), (6, "lower"))
        self.assertEqual(zoning.floors_allowed(0, road_width_m=8.0)["floors"], 9)
        self.assertIsInstance(zoning.floors_allowed(0, road_width_m=12.0), Insufficient)
        self.assertIsInstance(zoning.floors_allowed(None), Insufficient)

    def test_gfa(self):
        g = zoning.gfa(100, 3.0)
        self.assertAlmostEqual(g["gfa_m2"], 100 * 0.9 * 4)
        self.assertIsInstance(zoning.gfa(100, None), Insufficient)


if __name__ == "__main__":
    unittest.main()
