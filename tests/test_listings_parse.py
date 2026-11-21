import unittest

from vnrealty.listings import parse as P


class TestFold(unittest.TestCase):
    def test_fold(self):
        self.assertEqual(P.fold("Phường Hoà Quý"), "phuong hoa quy")
        self.assertEqual(P.fold("ĐƯỜNG  Đỗ Bá"), "duong do ba")
        self.assertEqual(P.fold(None), "")


class TestPrice(unittest.TestCase):
    def v(self, s, deal=None):
        return P.parse_price(s, deal)

    def test_totals(self):
        cases = {"3,25 tỷ": 3.25e9, "3.25 tỷ": 3.25e9, "3 tỷ 250": 3.25e9, "3 tỷ 250 triệu": 3.25e9, "3 tỷ 2": 3.2e9,
                 "3 tỷ 5 triệu": 3.005e9, "850 triệu": 8.5e8, "850tr": 8.5e8, "2.500.000.000 đ": 2.5e9,
                 "1.200 triệu": 1.2e9, "4,1 tỷ": 4.1e9, "Giá 18,5 tỷ": 18.5e9}
        for s, want in cases.items():
            r = self.v(s)
            self.assertEqual(r["value"], want, s)
            self.assertEqual(r["per"], "total", s)

    def test_per_m2_and_month(self):
        for s in ("45 tr/m²", "45 triệu/m2", "45 triệu / m²"):
            r = self.v(s)
            self.assertEqual((r["value"], r["per"]), (45e6, "m2"), s)
        r = self.v("12 triệu/tháng")
        self.assertEqual((r["value"], r["per"]), (12e6, "month"))
        self.assertEqual(self.v("12 triệu", deal="rent")["per"], "month")

    def test_negotiable_is_not_a_number(self):
        for s in ("Thỏa thuận", "Thoả thuận", "Liên hệ", "thương lượng"):
            r = self.v(s)
            self.assertIsNone(r["value"], s)
            self.assertTrue(r["negotiable"], s)

    def test_ambiguous_and_ranges(self):
        self.assertIsNone(self.v("3,5")["value"])          # no unit, not VND-sized
        self.assertIsNone(self.v("")["value"])
        r = self.v("3 - 3,5 tỷ")
        self.assertIsNone(r["value"])
        self.assertEqual((r["lo"], r["hi"]), (3e9, 3.5e9))
        self.assertEqual(self.v("3 tỷ 100 m2")["value"], 3e9)   # trailing area is not a fraction


class TestAreaDims(unittest.TestCase):
    def test_area(self):
        self.assertEqual(P.parse_area("103 m²"), 103)
        self.assertEqual(P.parse_area("103,5m2"), 103.5)
        self.assertEqual(P.parse_area("1.200 m2"), 1200)
        self.assertEqual(P.parse_area("5x20"), 100)
        self.assertEqual(P.parse_area("5 x 20m"), 100)
        self.assertEqual(P.parse_area("0,5 ha"), 5000)
        self.assertIsNone(P.parse_area("rộng rãi"))

    def test_dims(self):
        self.assertEqual(P.parse_dims("5m x 20m"), (5, 20))
        self.assertEqual(P.parse_dims("ngang 4,5m dài 18m"), (4.5, 18))
        self.assertIsNone(P.parse_dims("100 m2"))


class TestAccess(unittest.TestCase):
    def test_alley(self):
        self.assertEqual(P.parse_alley("kiệt 4m"), 4)
        self.assertEqual(P.parse_alley("hẻm 3m"), 3)
        self.assertEqual(P.parse_alley("đường vào 5m"), 5)
        self.assertEqual(P.parse_alley("Đường trước nhà: 7,5m"), 7.5)
        self.assertEqual(P.parse_alley("Bán nhà mặt tiền đường Lê Duẩn"), 0.0)
        self.assertEqual(P.parse_alley("lô đất mặt đường 10m5"), 0.0)
        self.assertIsNone(P.parse_alley("mặt tiền 5m"))     # a frontage width, not street frontage
        self.assertIsNone(P.parse_alley("kiệt ô tô"))       # fits a car, width unstated
        self.assertTrue(P.parse_access("kiệt ô tô")["car_access"])
        self.assertIsNone(P.parse_alley("nhà đẹp"))


class TestDetect(unittest.TestCase):
    def test_legal(self):
        self.assertEqual(P.detect_legal("Sổ đỏ/ Sổ hồng"), "so_hong")
        self.assertEqual(P.detect_legal("Sổ đỏ"), "so_do")
        self.assertEqual(P.detect_legal("Hợp đồng mua bán"), "hdmb")
        self.assertEqual(P.detect_legal("HĐMB"), "hdmb")
        self.assertEqual(P.detect_legal("giấy tay, vi bằng"), "giay_tay")
        self.assertEqual(P.detect_legal("Đã có sổ"), "co_so")

    def test_ptype(self):
        cases = {"Bán đất nền KĐT FPT": "land", "Bán nhà riêng kiệt 3m": "house", "Bán căn hộ chung cư": "apartment",
                 "Shophouse mặt biển": "shophouse", "Bán biệt thự": "villa", "Bán tòa căn hộ dịch vụ 20 phòng": "chdv",
                 "Cho thuê phòng trọ": "room", "Bán đất tặng nhà cấp 4": "land", "Bán nhà cấp 4 trên đất 100m2": "house",
                 "Sang nhượng quán cafe": "other"}
        for s, want in cases.items():
            self.assertEqual(P.detect_ptype(s), want, s)

    def test_corner_direction_deal(self):
        self.assertTrue(P.detect_corner("Lô góc 2 mặt tiền"))
        self.assertIsNone(P.detect_corner("Diện tích 100 m² Mặt tiền 5 m"))
        self.assertEqual(P.detect_direction("Hướng nhà: Đông Nam"), "SE")
        self.assertEqual(P.detect_direction("Đông - Nam"), "SE")
        self.assertEqual(P.detect_direction("Tây"), "W")
        self.assertIsNone(P.detect_direction("Nam cầu Cẩm Lệ đẹp"))
        self.assertEqual(P.detect_deal("Cho thuê nhà"), "rent")
        self.assertEqual(P.detect_deal("Bán nhà"), "sale")
        self.assertIsNone(P.detect_deal("Thuế phí bao sang tên"))


class TestPrivacy(unittest.TestCase):
    def test_phone(self):
        h = P.phone_hash("0900 000 001")
        self.assertEqual(h, P.phone_hash("+84 900.000.001"))
        self.assertEqual(len(h), 40)
        self.assertIsNone(P.phone_hash("123"))
        red = P.redact_phones("gọi 0900000001 nhé")
        self.assertNotIn("0900000001", red)
        self.assertIn("[phone:", red)
        self.assertEqual(P.find_phone_hashes("0900 000 001 / 0900000001"), [h])


class TestLabelsPostedPost(unittest.TestCase):
    def test_label_table(self):
        r = P.parse_label_table(["Mức giá", "3,25 tỷ", "Diện tích: 103 m²", "Hướng nhà", "Đông", "Mã tin", "41234567"])
        self.assertEqual(r, {"price": "3,25 tỷ", "area": "103 m²", "direction": "Đông", "site_id": "41234567"})
        self.assertEqual(P.parse_label_table(["Đường trước nhà", "7m"], {"alley": ["Đường trước nhà"]})["alley"], "7m")

    def test_posted(self):
        self.assertEqual(P.parse_posted("08/11/2026"), "2026-11-08")
        self.assertEqual(P.parse_posted("Hôm qua", "2026-11-10T09:00"), "2026-11-09")
        self.assertEqual(P.parse_posted("3 ngày trước", "2026-11-10"), "2026-11-07")
        self.assertIsNone(P.parse_posted("2 tháng trước", "2026-11-10"))
        self.assertIsNone(P.parse_posted("Hôm nay"))

    def test_parse_post(self):
        d = P.parse_post("Chính chủ bán lô đất 5x20 Hòa Quý, Ngũ Hành Sơn, sổ hồng, giá 2 tỷ 650. Lh 0905 000 111")
        self.assertEqual(d["ptype"], "land")
        self.assertEqual(d["price"], 2.65e9)
        self.assertEqual(d["area_m2"], 100)
        self.assertEqual(d["ward_code"], "ngu-hanh-son")
        self.assertEqual(d["legal"], "so_hong")
        self.assertGreaterEqual(d["confidence"], 0.9)
        self.assertNotIn("0905", d["title"])
        self.assertIsNotNone(d["phone_hash"])
        q = P.parse_post("Mọi người cho hỏi khu này có ngập không ạ?")
        self.assertLess(q["confidence"], 0.5)
        r = P.parse_post("Cho thuê căn hộ 2PN Sơn Trà 70m2 giá 12tr/tháng")
        self.assertEqual((r["kind"], r["price"], r["price_per"]), ("rent", 12e6, "month"))
        m = P.parse_post("Bán đất Hòa Hải 100m2 giá 45tr/m2")
        self.assertEqual((m["price_m2"], m["price"]), (45e6, 4.5e9))


if __name__ == "__main__":
    unittest.main()
