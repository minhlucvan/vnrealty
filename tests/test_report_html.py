import json
import tempfile
import unittest
from pathlib import Path

from vnrealty.report.fmt import pct, signed, vnd
from vnrealty.report.html import render_html, render_md, write_report

R = {"title": "Test", "subtitle": "s", "sections": [
    {"h": "K", "kind": "kpis", "items": [["Value", "3.25B"], ["Gap", {"v": "−5%", "cls": "neg"}]]},
    {"h": "T", "kind": "table", "cols": ["a", "b"], "rows": [["x|y", "1"]]},
    {"kind": "note", "text": "evil </script><script>alert(1)</script>"},
    {"kind": "chart", "labels": ["2025", "2026"], "series": [{"name": "p", "data": [1, 2]}]}]}


class TestReport(unittest.TestCase):
    def test_fmt(self):
        self.assertEqual(vnd(3.25e9), "3.25B")
        self.assertEqual(vnd(45e6), "45M")
        self.assertEqual(vnd(None), "—")
        self.assertEqual(pct(0.105), "10.5%")
        self.assertEqual(signed(-1e6)["cls"], "neg")

    def test_html_embeds_and_escapes(self):
        h = render_html(R)
        self.assertNotIn("</script><script>alert", h)
        start = h.index("const DATA = ") + len("const DATA = ")
        self.assertEqual(json.loads(h[start:h.index(";\n", start)])["title"], "Test")

    def test_md(self):
        m = render_md(R)
        self.assertIn("# Test", m)
        self.assertIn("x\\|y", m)

    def test_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = write_report(R, "market", "Hòa Quý", Path(d))
            self.assertTrue(Path(p["html"]).exists() and Path(p["md"]).exists())


if __name__ == "__main__":
    unittest.main()
