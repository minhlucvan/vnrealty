import json
import tempfile
import unittest

from vnrealty.infra.catalog import (add_evidence, catalysts_for, landuse_codes, near, parse_notes, seed_projects,
                                    upsert_project, zoning_note)
from vnrealty.projection.catalysts import paths
from vnrealty.store.db import connect


class TestCatalog(unittest.TestCase):
    def setUp(self):
        self.con = connect(":memory:")
        self.addCleanup(self.con.close)

    def test_seed_reference_every_project_cited(self):
        n = seed_projects(self.con)
        self.assertGreaterEqual(n, 10)
        for (pid,) in self.con.execute("SELECT id FROM project").fetchall():
            k = self.con.execute("SELECT COUNT(*) FROM project_evidence WHERE project_id = ?", (pid,)).fetchone()[0]
            self.assertGreaterEqual(k, 1, pid)
        self.assertEqual(seed_projects(self.con), n)    # idempotent
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM project").fetchone()[0], n)
        ev = self.con.execute("SELECT COUNT(*) FROM project_evidence").fetchone()[0]
        seed_projects(self.con)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM project_evidence").fetchone()[0], ev)

    def test_seed_refuses_uncited(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"projects": [{"id": "x", "evidence": []}]}, fh)
        with self.assertRaises(ValueError):
            seed_projects(self.con, fh.name)

    def test_near_and_catalysts(self):
        upsert_project(self.con, {"id": "a", "name_en": "A", "status": "approved", "lat": 16.0, "lng": 108.2,
                                  "radius_km": 2.0, "p_done": 0.5, "uplift": 0.1, "done_year": 2029,
                                  "basis": {"p_done": "judgement"}})
        upsert_project(self.con, {"id": "b", "status": "done", "lat": 16.001, "lng": 108.2, "p_done": 1, "uplift": 0.1,
                                  "done_year": 2026})
        upsert_project(self.con, {"id": "c", "status": "proposed", "lat": 16.002, "lng": 108.2})
        upsert_project(self.con, {"id": "far", "status": "approved", "lat": 16.5, "lng": 108.2, "p_done": 0.5,
                                  "uplift": 0.1, "done_year": 2029})
        add_evidence(self.con, "a", "https://example.test/a", "t", claim="c")
        self.assertIsNone(add_evidence(self.con, "a", "https://example.test/a", "t", claim="c"))
        rows = near(self.con, 16.0, 108.2, 1.0)
        self.assertEqual([r["id"] for r in rows], ["a", "b", "c"])
        self.assertEqual(rows[0]["evidence"][0]["url"], "https://example.test/a")
        out = catalysts_for(self.con, 16.0, 108.2, 1.0)
        self.assertEqual([c["id"] for c in out["catalysts"]], ["a"])
        self.assertEqual({s["id"] for s in out["skipped"]}, {"b", "c"})
        cat = out["catalysts"][0]
        self.assertEqual((cat["p"], cat["year"], cat["decay_km"]), (0.5, 2029, 2.0))
        p = paths({"y1": 0, "later": 0}, out["catalysts"], 3, 2026)
        self.assertAlmostEqual(p["bull"][3], 1.1, places=3)

    def test_upsert_merges_notes_and_updates(self):
        upsert_project(self.con, {"id": "a", "status": "proposed", "zoning": zoning_note(["ODT", "dgt"], "https://x.test", "2026-11-01")})
        upsert_project(self.con, {"id": "a", "status": "approved", "basis": {"status": "sourced"}})
        r = self.con.execute("SELECT status, notes FROM project WHERE id='a'").fetchone()
        n = parse_notes(r["notes"])
        self.assertEqual(r["status"], "approved")
        self.assertEqual(n["zoning"]["codes"], ["ODT", "DGT"])
        self.assertEqual(n["basis"]["status"], "sourced")

    def test_landuse_codes(self):
        codes = landuse_codes()
        for c in ("ODT", "ONT", "DGT", "CLN", "LUC", "TMD", "DKV"):
            self.assertIn(c, codes)
            self.assertTrue(codes[c]["vi"] and codes[c]["en"])
        with self.assertRaises(ValueError):
            zoning_note(["CXK"], "https://x.test", "2026-11-01")   # planning symbol, not a cadastral code

    def test_parse_notes_free_text(self):
        self.assertEqual(parse_notes("hello"), {"text": "hello"})
        self.assertEqual(parse_notes(None), {})


if __name__ == "__main__":
    unittest.main()
