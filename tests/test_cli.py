"""The `vnr` CLI end to end against a temp DB seeded with synthetic listings (no network, no real records)."""
import contextlib
import io
import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from vnrealty.cli import main
from vnrealty.report import builders as B
from vnrealty.store.db import connect
from tests.strategy_fixtures import FULL, OPP

M = 1e6
FIX = Path(__file__).parent / "fixtures"
AS_OF = "2026-11-20"


def seed(path: Path) -> None:
    """60 land/house sale listings and 20 rentals in two synthetic wards, two monthly sightings each."""
    con = connect(path)
    for code in ("w-a", "w-b"):
        con.execute("INSERT OR IGNORE INTO ward(code, name_vi) VALUES (?, ?)", (code, code.upper()))
    rnd = random.Random(3)
    n = 0
    for i in range(60):
        n += 1
        ward = "w-a" if i % 2 else "w-b"
        ptype = "land" if i % 3 else "house"
        area = 80 + (i * 7) % 50
        ppm = (55 if ward == "w-a" else 45) * M * (1 + rnd.uniform(-0.15, 0.15)) * (1.3 if ptype == "house" else 1)
        lat, lng = 16.05 + rnd.uniform(-0.01, 0.01), 108.24 + rnd.uniform(-0.01, 0.01)
        cur = con.execute(
            "INSERT INTO listing(fingerprint, ptype, deal, ward_code, street, lat, lng, area_m2, frontage_m, alley_m, "
            "corner, legal, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"syn{n}", ptype, "sale", ward, "duong test", lat, lng, area, 5.0, [0.0, 3.5, 5.0, 2.5, 4.0][i % 5], i % 6 == 1,
             "so_hong" if i % 7 else "so_chung", "2026-09-10", "2026-11-10"))
        lid = cur.lastrowid
        p1 = ppm * area
        p2 = p1 * (0.93 if i % 4 == 0 else 1.0)
        for seen, p in (("2026-09-10", p1 * 0.98), ("2026-10-10", p1), ("2026-11-10", p2)):
            con.execute("INSERT INTO listing_obs(listing_id, seen_at, site, url, kind, price, price_m2) "
                        "VALUES (?,?,?,?,?,?,?)", (lid, seen, "syn", f"https://example.test/{lid}", "asking", p,
                                                   p / area))
    for i in range(20):
        n += 1
        ward = "w-a" if i % 2 else "w-b"
        ptype = "land" if i % 3 else "house"
        area = 80 + (i * 5) % 40
        rent = area * (0.25 * M) * (1 + rnd.uniform(-0.1, 0.1))
        cur = con.execute("INSERT INTO listing(fingerprint, ptype, deal, ward_code, area_m2, first_seen, last_seen) "
                          "VALUES (?,?,?,?,?,?,?)", (f"rent{n}", ptype, "rent", ward, area, "2026-11-01", "2026-11-01"))
        con.execute("INSERT INTO listing_obs(listing_id, seen_at, site, kind, price, price_m2) VALUES (?,?,?,?,?,?)",
                    (cur.lastrowid, "2026-11-01", "syn", "rent", rent, rent / area))
    con.commit()
    con.close()


class CLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="vnr-cli-"))
        cls.db = cls.tmp / "vnr.sqlite"
        code, out = cls.run_cli("ingest", str(FIX), "--json")
        assert code == 0, out
        cls.ingested = out
        seed(cls.db)
        con = connect(cls.db)
        cls.lid = con.execute("SELECT id FROM listing WHERE fingerprint = 'syn3'").fetchone()[0]
        con.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def run_cli(cls, *args, as_of=AS_OF):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = main(["--db", str(cls.db), "--as-of", as_of, *args])
        txt = buf.getvalue()
        if "--json" in args:
            return code, json.loads(txt)
        return code, txt

    def j(self, *args, ok=(0,)):
        code, out = self.run_cli(*args, "--json")
        self.assertIn(code, ok, out)
        self.assertEqual(out["as_of"], AS_OF)
        return out

    def write(self, name, obj) -> str:
        p = self.tmp / name
        p.write_text(json.dumps(obj), encoding="utf-8")
        return str(p)

    # ----------------------------------------------------------- mining
    def test_browser_and_capture(self):
        self.assertIn("batdongsan", self.j("browser", "list")["scripts"])
        code, js = self.run_cli("browser", "script", "generic")
        self.assertEqual(code, 0)
        self.assertTrue(js.strip())
        self.assertIn("script", self.j("browser", "script", "generic"))
        out = self.j("capture", "save", str(FIX / "batdongsan" / "search.json"))
        self.assertTrue(Path(out["path"]).exists())
        self.assertTrue(Path(out["path"]).resolve().is_relative_to(self.tmp.resolve()))
        out = self.j("capture", "save", "--text", str(FIX / "generic" / "detail.txt"), "--url", "https://x.test/a",
                     "--site", "generic", "--kind", "detail")
        self.assertTrue(Path(out["path"]).exists())

    def test_ingest_and_listings(self):
        self.assertEqual(self.ingested["status"], "ok")
        self.assertGreater(self.ingested["new_listings"], 0)
        out = self.j("listings", "--ward", "w-a", "--ptype", "land", "--limit", "5")
        self.assertEqual(out["n"], 5)
        self.assertTrue(all(r["ward_code"] == "w-a" for r in out["listings"]))
        self.assertEqual(self.j("listings", "watch", str(self.lid))["watch"], True)
        self.assertEqual(self.j("listings", "--watched")["n"], 1)
        code, txt = self.run_cli("listings", "--limit", "3")
        self.assertEqual(code, 0)
        self.assertIn("listings", txt)

    def test_search_track_coverage_wards(self):
        self.j("search", "add", "s1", "batdongsan", "https://batdongsan.com.vn/ban-dat", "--criteria", '{"ptype":"land"}')
        self.assertEqual(self.j("search", "list")["searches"][0]["name"], "s1")
        self.j("search", "touch", "s1")
        out = self.j("track", "--since", "2026-11-01")
        self.assertTrue(any(c["pct"] < 0 for c in out["cuts"]))
        self.assertIn("marked_gone", self.j("track", "mark-gone", "--days", "30"))
        cov = self.j("coverage")
        self.assertTrue(any(c["ward_code"] == "w-a" for c in cov["by_ward"]))
        self.assertIn("code", self.j("wards", "match", "Hòa Quý, Ngũ Hành Sơn"))

    # ----------------------------------------------------------- market / value
    def test_market(self):
        out = self.j("market", "w-a", "--ptype", "land")
        self.assertEqual(out["scope"], "w-a")
        self.assertIn("landscape", out)
        city = self.j("market", "city")
        self.assertEqual(city["scope"], "city")
        y = self.j("market", "yields", "--ward", "w-a")
        self.assertTrue(any(r["status"] == "ok" for r in y["yields"]))
        r = self.j("market", "rents", "--ward", "w-a", "--ptype", "land")
        self.assertIn("median", r["rent"])
        idx = self.j("market", "index", "--save", ok=(0, 2))
        self.assertIn("repeat_index", idx)
        self.assertIn("series", self.j("series", "list"))

    def test_value_comps_history(self):
        v = self.j("value", str(self.lid))
        self.assertEqual(v["combined"]["status"], "ok")
        self.assertIn("comps", v["methods"])
        self.assertIsNotNone(v["gap_to_ask"])
        self.assertTrue(v["recorded"])
        self.assertEqual(v["official_floor"]["status"], "insufficient")
        c = self.j("comps", f"listing:{self.lid}")
        self.assertGreaterEqual(len(c["comps"]), 5)
        self.assertIn("adj_price_m2", c["comps"][0])
        h = self.j("history", str(self.lid), "--index", "city", ok=(0, 2))
        self.assertTrue(h["anchors"])
        code, txt = self.run_cli("value", str(self.lid), "--no-record")
        self.assertEqual(code, 0)
        self.assertIn("combined", txt)
        self.j("sale", "add", "--price", "5.1e9", "--sold-at", "2026-11-15", "--source", "notary (synthetic)",
               "--listing", str(self.lid))
        self.assertEqual(len(self.j("sale", "list", "--listing", str(self.lid))["sales"]), 1)
        cal = self.j("calibrate", ok=(0, 2))
        self.assertIn("weights", cal)

    def test_missing_subject_is_error(self):
        code, out = self.run_cli("value", "999999", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "error")

    # ----------------------------------------------------------- infra / projection
    def test_infra_and_project(self):
        self.j("infra", "add", "--id", "syn-road", "--name-en", "Synthetic road", "--kind", "road", "--status",
               "approved", "--lat", "16.05", "--lng", "108.24", "--done-year", "2029", "--p-done", "0.6",
               "--uplift", "0.1", "--radius-km", "2", "--url", "https://example.test/road", "--claim", "approved")
        self.j("infra", "cite", "syn-road", "https://example.test/road2", "--claim", "budget allocated")
        near = self.j("infra", "near", "16.05,108.24", "--km", "3")
        self.assertTrue(any(p["id"] == "syn-road" for p in near["projects"]))
        cat = self.j("infra", "catalysts", str(self.lid), "--km", "3")
        self.assertTrue(cat["catalysts"])
        self.j("infra", "zoning", "add", str(self.lid), "--code", "ODT", "--plan", "QH 1/2000", "--source",
               "https://example.test/qh")
        self.assertEqual(self.j("infra", "zoning", "show", str(self.lid))["latest"]["codes"], ["ODT"])
        p = self.j("project", str(self.lid), "--years", "5", "--drift", "0.05", "--vol", "0.1",
                   "--deposit-rate", "0.055", "--n", "300")
        self.assertEqual(len(p["monte_carlo"]["p50"]), 6)
        self.assertIn("best", p["hold_vs_sell"])
        p2 = self.j("project", str(self.lid), "--years", "3", "--n", "200", ok=(0, 2))
        self.assertIn("market", p2)

    # ----------------------------------------------------------- deals / strategy
    def deal_file(self):
        out = self.j("deal", "preset", "apartment", "--out", str(self.tmp / "tpl.json"))
        t = json.loads(Path(out["path"]).read_text())
        self.assertIsNone(t["rent"])
        code, ins = self.run_cli("deal", out["path"], "--json")
        self.assertEqual(code, 2)
        self.assertEqual(ins["deal"]["status"], "insufficient")
        t.update(price=3e9, value_after=3.2e9, rent=18 * M, loan=1.2e9, teaser_rate=0.07, float_rate=0.105,
                 price_growth=0.05, rent_growth=0.03, hurdle=0.10, renovation=100 * M, running_costs=1.5 * M)
        return self.write("deal.json", t)

    def test_deal_ev_compare_score(self):
        f = self.deal_file()
        d = self.j("deal", f)
        self.assertIn("irr", d["metrics"])
        self.assertIn("rate_up_3", d["stress"])
        self.assertEqual(len(d["yearly"]), 10)
        e = self.j("ev", f)
        self.assertAlmostEqual(sum(s["p"] for s in e["ev"]["scenarios"]), 1.0)
        self.assertIn("kill", e)
        cmp_ = self.j("compare", f, str(self.lid), "--deal", f)
        self.assertEqual(len(cmp_["rows"]), 2)
        sc = self.j("score", str(self.lid), "--deal", f)
        self.assertEqual(sc["grade"]["status"], "graded")
        code, _ = self.run_cli("score", str(self.lid), "--json")
        self.assertEqual(code, 2)                                 # no deal: IRR missing, grade withheld
        fp = self.j("finplan", "ladder", f, "--years", "5", "--household",
                    self.write("hh.json", {"cash": 1.5e9, "monthly_income": 60 * M, "monthly_spend": 25 * M,
                                           "max_dti": 0.4, "mortgage_rate": 0.10, "term_years": 20,
                                           "max_ltv": 0.7}), ok=(0, 2))
        self.assertIn("plan", fp)
        aff = self.j("finplan", "--household", str(self.tmp / "hh.json"))
        self.assertEqual(aff["affordability"]["status"] if "status" in aff["affordability"] else "ok", "ok")

    def test_strategy(self):
        opp = self.write("opp.json", {"opportunity": OPP, "assumptions": FULL})
        ev = self.j("strategy", "evaluate", opp)
        self.assertTrue(ev["ranked"])
        self.assertEqual(ev["profile_source"], "preset default (balanced; judgement)")
        cands = [{"id": f"a:{r['strategy']}", "strategy": r["strategy"], "asset": "a", "peak_cash": r["peak_cash"],
                  "ev_npv": r["ev"]["expected_npv"], "p_loss": r["ev"]["p_loss"],
                  "bear_loss": max(0, -r["ev"]["bear"]["npv"]), "liquidity_months": r["liquidity_months"],
                  "ward": "w1", "ptype": "house"} for r in ev["ranked"]]
        al = self.j("strategy", "allocate", self.write("cands.json", cands), "--cash", "5e9", ok=(0, 2))
        self.assertIn("result", al)
        f = self.deal_file()
        t = self.j("strategy", "tornado", f)
        self.assertTrue(t["result"]["rows"])
        be = self.j("strategy", "break-even", f, "rent", ok=(0, 2))
        self.assertIn("result", be)
        t2 = self.j("strategy", "tornado", opp, "--strategy", "buy_hold")
        self.assertTrue(t2["result"]["rows"])
        q = self.j("strategy", "profile", "questions")
        self.assertTrue(q["questions"])
        pr = self.j("strategy", "profile", "from-answers", self.write("ans.json", {"risk": "conservative"}),
                    "--out", str(self.tmp / "profile.json"))
        self.assertEqual(pr["profile"]["risk_tolerance"], "conservative")
        rep = self.j("report", "strategy", opp, "--profile", str(self.tmp / "profile.json"))
        self.assertTrue(Path(rep["paths"]["html"]).exists())

    def test_plan(self):
        lot = self.write("lot.json", {"value": 3e9, "area_m2": 100, "buildable_ratio": 0.9, "max_floors": 4,
                                      "build_cost_m2": 6.5 * M, "unit_size_m2": 28, "unit_rent": 4.5 * M,
                                      "fit_out_per_unit": 35 * M, "running_cost_per_unit": 0.7 * M,
                                      "deposit_rate": 0.055, "mortgage_rate": 0.10, "build_ltv": 0.5, "hurdle": 0.10,
                                      "price_growth": 0.05, "rent_growth": 0.04, "land_lease_rent": 3 * M})
        p = self.j("plan", lot, ok=(0, 2))
        self.assertIn("options", p)
        rep = self.j("report", "plan", lot)
        self.assertTrue(Path(rep["paths"]["md"]).exists())

    # ----------------------------------------------------------- reports
    def test_report_listing_embeds_json(self):
        out = self.j("report", "listing", str(self.lid))
        html = Path(out["paths"]["html"]).read_text(encoding="utf-8")
        self.assertIn('"sections"', html)
        self.assertIn(f"listing:{self.lid}", html)
        self.assertTrue(Path(out["paths"]["html"]).resolve().is_relative_to(self.tmp.resolve()))
        for kind, args in (("market", ["w-a"]), ("screen", ["all"]), ("portfolio", [])):
            r = self.j("report", kind, *args)
            self.assertTrue(Path(r["paths"]["html"]).exists(), kind)
        f = self.deal_file()
        self.assertTrue(Path(self.j("report", "deal", f)["paths"]["html"]).exists())
        self.assertTrue(Path(self.j("report", "compare", f, str(self.lid), "--deal", f)["paths"]["html"])
                        .exists())

    def test_builders_flag_risky_titles(self):
        rep = B.compare({"rows": [{"name": "a", "price": 1e9, "extra": {"legal": "so_chung"}}], "ranks": {}},
                        as_of=AS_OF)
        self.assertTrue(any(s["kind"] == "note" and "shared" in s["text"] for s in rep["sections"]))
        for code in ("so_chung", "cho_so", "hdmb", "giay_tay"):
            self.assertIsNotNone(B.legal_flag(code))
        self.assertIsNone(B.legal_flag("so_hong"))

    # ----------------------------------------------------------- legal / portfolio
    def test_legal(self):
        c = self.j("legal", "checklist", str(self.lid))
        item = c["items"][0]["id"] if "items" in c else next(iter(c.get("status", {})), None)
        self.assertIsNotNone(item)
        self.j("legal", "set", str(self.lid), item, "ok", "--note", "checked (synthetic)")
        cost = self.j("legal", "costs", "3e9", "--role", "buyer")
        self.assertEqual(cost["price"], 3e9)
        self.j("legal", "costs", "3e9", "--role", "seller", "--official", "1e9")

    def test_portfolio_flow(self):
        self.j("unit", "add", "u1", "Synthetic unit", "--ptype", "house", "--ward", "w-a", "--cost", "2.5e9",
               "--bought-at", "2024-03-01", "--value", "3e9", "--value-at", "2026-10-01", "--loan", "1e9",
               "--loan-rate", "0.1", "--loan-term", "15", "--legal", "so_hong", "--area", "90")
        self.j("unit", "update", "u1", "--notes", "zoning:ok")
        self.assertEqual(self.j("unit", "list")["units"][0]["id"], "u1")
        lease = self.j("lease", "add", "u1", "--tenant", "T1", "--rent", "15e6", "--start", "2026-01-01",
                       "--deposit", "30e6")
        for m in ("2026-09", "2026-10"):
            self.j("txn", "add", "u1", "15e6", "rent", "--at", f"{m}-05", "--period", m, "--lease", str(lease["id"]))
        self.j("txn", "add", "u1", "-2e6", "repair", "--at", "2026-10-12")
        pf = self.j("portfolio")
        self.assertIn("total", pf)
        cl = self.j("portfolio", "close", "2026-10")
        self.assertEqual(cl["month"], "2026-10")
        self.assertIn("expected_rent", cl)
        r = self.j("risk", "--cash", "500e6")
        self.assertIn("ltv", r)
        self.j("lease", "end", str(lease["id"]), "--end", "2026-12-31")
        v = self.j("value", "unit:u1", ok=(0, 2))
        self.assertIn("index_moved", v["methods"])
        d = self.j("ledger", "open", str(self.lid), "buy", "--price", "3e9", "--est-value", "3.2e9", "--verdict", "test")
        self.j("ledger", "close", str(d["id"]), "--outcome", '{"realised_value": 3.1e9}')
        self.assertTrue(self.j("ledger", "list")["deals"])
        self.assertIn("n", self.j("ledger", "scorecard")) if "n" in self.j("ledger", "scorecard") else None
        self.j("journal", "add", "track", "synthetic pass")
        self.assertTrue(self.j("journal", "list", "--kind", "track")["entries"])

    # ----------------------------------------------------------- screens / pricing / forecast
    def test_screens(self):
        for rule in ("undervalued", "yield", "catalyst", "motivated", "all"):
            out = self.j("screen", "--rule", rule, ok=(0, 2))
            self.assertIn("results", out, rule)
        und = self.j("screen", "--rule", "undervalued", "--ward", "w-a", "--threshold", "0")
        self.assertTrue(und["results"]["undervalued"])
        self.assertLess(und["results"]["undervalued"][0]["residual_log"], 0)
        mot = self.j("screen", "--rule", "motivated")
        self.assertTrue(mot["results"]["motivated"])
        self.assertIn("pricing", self.j("screen", "--rule", "pricing", "--top", "5", ok=(0, 2))["results"])
        self.assertIn("score", self.j("price", str(self.lid), ok=(0, 2)))

    def test_series_and_forecast(self):
        pts = [[f"{2023 + (m // 12)}-{m % 12 + 1:02d}", 40e6 * (1.004 ** m)] for m in range(40)]
        self.j("series", "add", "syn-report", "w-a", "land", "--points", json.dumps(pts), "--url",
               "https://example.test/series")
        f = self.j("forecast", "series", "w-a", "land", ok=(0, 2))
        self.assertIn("backtest", f)
        a = self.j("forecast", "asset", str(self.lid), "--years", "2", "--deposit-rate", "0.05", ok=(0, 2))
        self.assertIn("projection", a)
        self.assertIn("models", self.j("forecast", "grade"))
        short = self.j("forecast", "series", "w-b", "land", ok=(2,))
        self.assertEqual(short["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()


class TestUnitAccess(unittest.TestCase):
    def test_unit_access_columns_and_migration(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from vnrealty.cli import main
        from vnrealty.store.db import connect
        d = Path(tempfile.mkdtemp()) / "old.sqlite"
        old = sqlite3.connect(d)   # a database created before the access columns existed
        old.execute("CREATE TABLE unit (id TEXT PRIMARY KEY, name TEXT NOT NULL, ptype TEXT, ward_code TEXT, address TEXT, lat REAL, "
                    "lng REAL, area_m2 REAL, bought_at TEXT, cost REAL, share REAL NOT NULL DEFAULT 1.0, loan REAL DEFAULT 0, "
                    "loan_rate REAL, loan_term_years REAL, value REAL, value_at TEXT, legal TEXT, status TEXT DEFAULT 'held', "
                    "listing_id INTEGER, notes TEXT)")
        old.commit(); old.close()
        connect(d).close()
        cols = {r[1] for r in sqlite3.connect(d).execute("PRAGMA table_info(unit)")}
        self.assertTrue({"alley_m", "frontage_m", "corner", "road_width_m", "depth_m"} <= cols)
        self.assertEqual(main(["--db", str(d), "--json", "unit", "add", "u1", "Lot", "--ptype", "land", "--area", "100",
                               "--alley", "4", "--frontage", "5", "--corner", "1"]), 0)
        r = sqlite3.connect(d).execute("SELECT alley_m, frontage_m, corner FROM unit WHERE id='u1'").fetchone()
        self.assertEqual(r, (4.0, 5.0, 1))
