import unittest

from vnrealty.listings.dedupe import extract_street, fingerprint
from vnrealty.types import ListingObs


def o(**kw):
    base = dict(site="batdongsan", seen_at="2026-11-01", ptype="house", area_m2=100.2, frontage_m=5.0)
    base.update(kw)
    return ListingObs(**base)


class TestStreet(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(extract_street("Kiệt 12 Lê Văn Hiến, Hòa Quý"), "le van hien")
        self.assertEqual(extract_street("K12/3 Lê Văn Hiến, Phường Hòa Quý"), "le van hien")
        self.assertEqual(extract_street("Đường Văn Tiến Dũng, Phường Hòa Xuân"), "van tien dung")
        self.assertEqual(extract_street("123 Đường 2 Tháng 9, Hải Châu"), "2 thang 9")
        self.assertIsNone(extract_street("Phường Hòa Quý, Quận Ngũ Hành Sơn"))
        self.assertIsNone(extract_street("Hòa Quý, Ngũ Hành Sơn, Đà Nẵng"))
        self.assertIsNone(extract_street(None))


class TestFingerprint(unittest.TestCase):
    def test_same_property_two_sites_two_prices(self):
        a = o(site="batdongsan", site_id="1", price=3.2e9, address="Kiệt 12 Lê Văn Hiến, Phường Hòa Quý")
        b = o(site="chotot", site_id="9", price=3.0e9, address="K45 Lê Văn Hiến, Hoà Quý, Ngũ Hành Sơn", area_m2=99.8,
              frontage_m=5.04)
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertTrue(fingerprint(a).startswith("fp:"))

    def test_geo_cell(self):
        a = o(lat=16.00110, lng=108.25110)
        b = o(lat=16.00112, lng=108.25113, site="chotot")
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertNotEqual(fingerprint(a), fingerprint(o(lat=16.0100, lng=108.2511)))

    def test_non_collisions(self):
        base = o(address="Lê Văn Hiến, Hòa Quý")
        self.assertNotEqual(fingerprint(base), fingerprint(o(address="Lê Văn Hiến, Hòa Quý", area_m2=120)))
        self.assertNotEqual(fingerprint(base), fingerprint(o(address="Lê Văn Hiến, Hòa Quý", frontage_m=6.0)))
        self.assertNotEqual(fingerprint(base), fingerprint(o(address="Lê Văn Hiến, Hòa Quý", ptype="land")))
        self.assertNotEqual(fingerprint(base), fingerprint(o(address="Lê Văn Hiến, Hòa Quý", kind="rent")))
        self.assertNotEqual(fingerprint(base), fingerprint(o(address="Lê Văn Hiến, Hòa Xuân")))
        # Hòa Hải and Hòa Quý are both old wards of the new Ngũ Hành Sơn ward: the key uses the NEW unit
        self.assertEqual(fingerprint(base), fingerprint(o(address="Lê Văn Hiến, Hòa Hải")))
        self.assertNotEqual(fingerprint(base), fingerprint(o(address="Trần Đại Nghĩa, Hòa Quý")))

    def test_fallbacks_never_merge_unknowns(self):
        # no location → the site id, not a shared attribute key
        a, b = o(site_id="111"), o(site_id="222")
        self.assertEqual(fingerprint(a), "site:batdongsan:111")
        self.assertNotEqual(fingerprint(a), fingerprint(b))
        self.assertTrue(fingerprint(o(url="https://x.vn/a?utm=1")).startswith("url:"))
        self.assertEqual(fingerprint(o(url="https://x.vn/a?utm=1")), fingerprint(o(url="https://x.vn/a")))
        self.assertTrue(fingerprint(o(title="Bán nhà")).startswith("raw:"))
        # price never enters the key
        self.assertEqual(fingerprint(o(site_id="1", price=1e9)), fingerprint(o(site_id="1", price=2e9)))


if __name__ == "__main__":
    unittest.main()
