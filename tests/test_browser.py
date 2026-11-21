import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from vnrealty import browser
from vnrealty.listings.parse import phone_hash

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
URLS = {"batdongsan": "https://batdongsan.com.vn/nha-dat-ban-da-nang",
        "batdongsan_detail": "https://batdongsan.com.vn/ban-nha-rieng-pr41234567",
        "nhatot": "https://www.nhatot.com/mua-ban-bat-dong-san-da-nang", "chotot": "https://www.nhatot.com/123456789.htm",
        "alonhadat": "https://alonhadat.com.vn/nha-dat/can-ban.html", "guland": "https://guland.vn/post/ban-dat-123456",
        "muaban": "https://muaban.net/bat-dong-san/ban-nha-id71234567", "bds68": "https://bds68.com.vn/ban-nha/12345678",
        "generic": "https://nhadat.example.vn/tin/123456.html",
        "maps": "https://www.google.com/maps/place/X/@16.0,108.2,17z/data=!3d16.0612!4d108.2234",
        "zoning": "https://guland.vn/soi-quy-hoach/da-nang", "social": "https://www.facebook.com/groups/1/"}


class TestBundling(unittest.TestCase):
    def test_list_and_bundle(self):
        names = browser.list_scripts()
        for n in ("batdongsan", "chotot", "alonhadat", "guland", "muaban", "bds68", "generic", "maps", "zoning", "social"):
            self.assertIn(n, names)
        js = browser.script("batdongsan_detail")
        self.assertTrue(js.startswith("(() => {") and js.rstrip().endswith("})()"))
        self.assertIn("function parseLabelTable", js)
        with self.assertRaises(KeyError):
            browser.script("nope")

    def test_scripts_are_read_only(self):
        for n in browser.list_scripts():
            body = (browser.BROWSER_DIR / f"{n}.js").read_text(encoding="utf-8")
            for bad in ("fetch(", "XMLHttpRequest", ".click()", ".submit()", "localStorage", "sendBeacon", "WebSocket"):
                self.assertNotIn(bad, body, f"{n}.js uses {bad}")
        core = (browser.BROWSER_DIR / "lib" / "core.js").read_text(encoding="utf-8")
        for bad in ("fetch(", "XMLHttpRequest", ".click(", ".submit(", "localStorage"):
            self.assertNotIn(bad, core)

    def test_self_contained_scripts_are_not_wrapped(self):
        self.assertTrue(browser.is_self_contained("/* doc */\n(() => { return 1; })()"))
        self.assertFalse(browser.is_self_contained("/* doc */\nconst SITE = 'x';\nreturn 1;"))
        if "nhatot" in browser.list_scripts():
            self.assertNotIn("function parseLabelTable", browser.script("nhatot"))

    def test_save_capture_strings(self):
        with tempfile.TemporaryDirectory() as d:
            s = json.dumps({"site": "batdongsan", "url": "u", "seen_at": "2026-11-13T08:00:00Z", "kind": "srp",
                            "items": [], "columns": []})
            self.assertTrue(browser.save_capture(s, d).name.endswith(".json"))
            p = browser.save_capture("#total=0|url=https://www.nhatot.com/x|seen_at=2026-11-13T09:00:00Z", d)
            self.assertEqual(p.suffix, ".txt")
            self.assertEqual(p.parent.parent.name, "chotot")

    def test_save_capture(self):
        with tempfile.TemporaryDirectory() as d:
            obj = {"site": "batdongsan", "url": "https://batdongsan.com.vn/x-pr1", "seen_at": "2026-11-21T10:00:00Z",
                   "kind": "detail", "items": [], "warnings": []}
            p = browser.save_capture(obj, d)
            self.assertEqual(p.parent.name, "2026-11-21")
            self.assertEqual(p.parent.parent.name, "batdongsan")
            self.assertEqual(json.loads(p.read_text())["site"], "batdongsan")
            with self.assertRaises(ValueError):
                browser.save_capture({"site": "x"}, d)
            t = browser.save_text_capture({"url": "https://x.vn/1", "site": "x", "seen_at": "2026-11-21", "kind": "detail"},
                                          "Giá 3 tỷ, gọi 0900000001", d)
            body = t.read_text()
            self.assertIn("# url: https://x.vn/1", body)
            self.assertNotIn("0900000001", body)


@unittest.skipUnless(NODE, "node not installed")
class TestNode(unittest.TestCase):
    def test_core_unit_tests(self):
        r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "test_core.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["sha1_phone"], phone_hash("0900 000 001"))  # JS and Python hash phones identically

    def test_bundles_syntax_and_smoke(self):
        with tempfile.TemporaryDirectory() as d:
            body = os.path.join(d, "body.txt")
            Path(body).write_text("Mức giá\n3,25 tỷ\nDiện tích\n103 m²\nĐịa chỉ: Hòa Quý, Ngũ Hành Sơn\nLiên hệ 0900000001",
                                  encoding="utf-8")
            for n in browser.list_scripts():
                p = os.path.join(d, f"{n}.js")
                Path(p).write_text(browser.script(n), encoding="utf-8")
                r = subprocess.run([NODE, "--check", p], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{n}: {r.stderr}")
                r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "smoke_bundle.js"), p, URLS[n], body],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{n}: {r.stderr}")
                env = json.loads(r.stdout)
                if isinstance(env, str) and env.startswith("#total="):     # nhatot.js compact rows
                    continue
                if isinstance(env, str):                                  # scripts may return JSON.stringify(env)
                    env = json.loads(env)
                self.assertLessEqual({"site", "url", "seen_at", "kind", "items", "warnings"}, set(env), n)
                self.assertIn(env["kind"], ("detail", "search", "srp", "map", "zoning", "social"))
                self.assertNotIn("0900000001", r.stdout, n)
            # detail pages read the label table from body text
            bd = json.loads(subprocess.run([NODE, str(ROOT / "tests" / "js" / "smoke_bundle.js"), os.path.join(d, "batdongsan_detail.js"),
                                            URLS["batdongsan_detail"], body], capture_output=True, text=True).stdout)
            self.assertEqual(bd["items"][0]["price_text"], "3,25 tỷ")
            self.assertEqual(bd["items"][0]["site_id"], "41234567")


if __name__ == "__main__":
    unittest.main()
