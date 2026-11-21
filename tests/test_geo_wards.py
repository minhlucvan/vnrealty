import json
import unittest

from vnrealty.geo import wards as W
from vnrealty.store.db import connect


class TestWardData(unittest.TestCase):
    def test_reference_file(self):
        data = json.loads(W.WARDS_PATH.read_text(encoding="utf-8"))
        self.assertTrue(data["sources"])
        self.assertIn("1659/NQ-UBTVQH15", json.dumps(data["sources"], ensure_ascii=False))
        ws = data["wards"]
        self.assertEqual(len({w["code"] for w in ws}), len(ws))
        for w in ws:
            self.assertIn(w["verified"], (True, False))
            self.assertIsInstance(w["old_wards"], list)
            if w["lat"] is not None:
                self.assertTrue(15 < w["lat"] < 17)
        old_dn = {"Hải Châu", "Thanh Khê", "Sơn Trà", "Ngũ Hành Sơn", "Liên Chiểu", "Cẩm Lệ", "Hòa Vang"}
        self.assertTrue(old_dn <= {d for w in ws for d in w.get("old_districts") or [w["old_district"]]})

    def test_seed(self):
        con = connect(":memory:")
        n = W.seed_wards(con)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM ward").fetchone()[0], n)
        self.assertEqual(W.seed_wards(con), n)  # idempotent
        r = con.execute("SELECT name_vi, old_ward FROM ward WHERE code='ngu-hanh-son'").fetchone()
        self.assertIn("Hòa Quý", r["old_ward"])


class TestMatch(unittest.TestCase):
    def test_new_and_old_names(self):
        cases = {"Hòa Quý, Ngũ Hành Sơn": "ngu-hanh-son", "P. Hoà Quý": "ngu-hanh-son",
                 "Phường Hải Châu": "hai-chau", "phuong hoa cuong": "hoa-cuong",
                 "Kiệt 12 Lê Văn Hiến, Phường Khuê Mỹ, Quận Ngũ Hành Sơn, Đà Nẵng": "ngu-hanh-son",
                 "Thạc Gián, Thanh Khê": "thanh-khe", "Phường Sơn Trà": "son-tra",
                 "bán nhà kiệt hoà khánh nam liên chiểu": "hoa-khanh", "Phước Mỹ, Sơn Trà": "an-hai",
                 "Ngũ Hành Sơn": "ngu-hanh-son"}
        for t, want in cases.items():
            self.assertEqual(W.match_ward(t), want, t)

    def test_never_guess(self):
        for t in ("Sơn Trà, Đà Nẵng", "Hải Châu", "Hòa Liên, Hòa Vang", "Thanh Bình", "Hà Nội", "", None):
            self.assertIsNone(W.match_ward(t), t)
        d = W.match_ward_detail("Q. Sơn Trà")
        self.assertEqual(d["how"], "ambiguous")
        self.assertEqual(d["candidates"], ["an-hai", "son-tra"])
        # a district narrows an ambiguous old ward name
        self.assertEqual(W.match_ward("Thanh Bình, Hải Châu"), "hai-chau")
        self.assertEqual(W.match_ward_detail("Ngũ Hành Sơn")["how"], "old_district")


class TestGeo(unittest.TestCase):
    def test_haversine(self):
        self.assertAlmostEqual(W.haversine_km(16.0, 108.0, 16.0, 108.0), 0.0)
        self.assertAlmostEqual(W.haversine_km(16.0, 108.0, 17.0, 108.0), 111.2, delta=0.2)

    def test_cell(self):
        self.assertEqual(W.cell(16.0501, 108.2201), W.cell(16.05011, 108.22012))
        self.assertNotEqual(W.cell(16.0501, 108.2201), W.cell(16.0601, 108.2201))
        self.assertTrue(W.cell(16.05, 108.22, 50).startswith("g50:"))


if __name__ == "__main__":
    unittest.main()
