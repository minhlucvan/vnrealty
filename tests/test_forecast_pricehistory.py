"""browser/pricehistory.js: syntax, its node unit tests, a stub-DOM smoke run, and the capture → series round trip."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from vnrealty import browser
from vnrealty.forecast.series import from_capture

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
JS = ROOT / "browser" / "pricehistory.js"


class TestStatic(unittest.TestCase):
    def test_self_contained_and_read_only(self):
        src = JS.read_text(encoding="utf-8")
        self.assertTrue(browser.is_self_contained(src))
        for bad in ("fetch(", "XMLHttpRequest", ".click(", ".submit(", "localStorage", "sendBeacon", "WebSocket"):
            self.assertNotIn(bad, src)
        self.assertIn("pricehistory", browser.list_scripts())


@unittest.skipUnless(NODE, "node not installed")
class TestNode(unittest.TestCase):
    def test_check_and_unit_tests(self):
        r = subprocess.run([NODE, "--check", str(JS)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "test_pricehistory.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreaterEqual(json.loads(r.stdout.strip().splitlines()[-1])["passed"], 7)

    def test_highcharts_page_round_trip(self):
        harness = """
const fs = require('fs');
global.location = { href: 'https://batdongsan.com.vn/gia-dat-da-nang', hostname: 'batdongsan.com.vn' };
global.document = { querySelector: () => null, querySelectorAll: () => [], body: { innerText: 'Giá 40 triệu/m²' }, title: 'Giá đất Đà Nẵng' };
global.window = { Highcharts: { charts: [{ xAxis: [{ categories: ['T1/2025','T2/2025','T3/2025'] }],
  series: [{ name: 'Đất nền', data: [{ category: 'T1/2025', y: 40 }, { category: 'T2/2025', y: 41 }, { category: 'T3/2025', y: 42.5 }] }] }] } };
process.stdout.write(JSON.stringify(eval(fs.readFileSync(process.argv[2], 'utf8'))));
"""
        with tempfile.TemporaryDirectory() as d:
            h = os.path.join(d, "h.js")
            Path(h).write_text(harness, encoding="utf-8")
            r = subprocess.run([NODE, h, str(JS)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            cap = json.loads(r.stdout)
        self.assertEqual(cap["site"], "batdongsan")
        self.assertEqual(cap["kind"], "series")
        rows = from_capture(cap)
        self.assertEqual(rows[0]["points"], [("2025-01", 40.0), ("2025-02", 41.0), ("2025-03", 42.5)])
        self.assertEqual((rows[0]["unit"], rows[0]["multiplier"]), ("vnd_m2", 1e6))
        self.assertEqual(rows[0]["scope_text"], "Giá đất Đà Nẵng")


if __name__ == "__main__":
    unittest.main()
