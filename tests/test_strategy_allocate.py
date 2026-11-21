"""allocate: exact knapsack with concentration, risk and liquidity limits; greedy + repair beyond 18; reports."""
import unittest

from vnrealty.strategy.allocate import allocate, candidates_from_evaluation
from vnrealty.strategy.evaluate import evaluate_all
from vnrealty.strategy.profile import InvestorProfile
from vnrealty.types import Insufficient
from tests.strategy_fixtures import FULL, OPP

LOOSE = InvestorProfile(risk_tolerance="aggressive", time_available="active", monthly_outgoings=0.0,
                        max_single_asset_share=1.0, max_ward_share=1.0, max_ptype_share=1.0, risk_budget_share=10.0,
                        max_avg_exit_months=100)


def cand(i, peak, ev, ward="w", ptype="house", bear=0.0, liq=6, **kw):
    return {"id": i, "strategy": "buy_hold", "peak_cash": peak, "ev_npv": ev, "p_loss": 0.0, "bear_loss": bear,
            "liquidity_months": liq, "ward": ward, "ptype": ptype, **kw}


def ids(r):
    return sorted(c["id"] for c in r["chosen"])


class Exact(unittest.TestCase):
    def test_knapsack_beats_greedy_ratio(self):
        # ratio order picks A (5/6) first and then nothing fits; the optimum is B + C = 8
        r = allocate([cand("A", 6, 5), cand("B", 5, 4), cand("C", 5, 4)], 10, LOOSE)
        self.assertEqual(r["method"], "exact")
        self.assertEqual(ids(r), ["B", "C"])
        self.assertEqual(r["totals"]["ev_npv"], 8)
        self.assertEqual(r["marginal"]["candidate"]["id"], "A")
        self.assertEqual(r["binding"][0], "cash")

    def test_reserve_reduces_budget(self):
        p = InvestorProfile(**{**LOOSE.__dict__, "monthly_outgoings": 1.0, "min_liquidity_months": 2})
        r = allocate([cand("A", 6, 5), cand("B", 5, 4), cand("C", 5, 4)], 10, p)
        self.assertEqual(r["totals"]["reserve"], 2)
        self.assertEqual(ids(r), ["A"])                             # budget 8: A (5) beats B or C alone (4)

    def test_ward_concentration(self):
        p = InvestorProfile(**{**LOOSE.__dict__, "max_ward_share": 0.5})
        r = allocate([cand("A", 4, 3, ward="x"), cand("B", 4, 3, ward="x"), cand("C", 3, 1, ward="y")], 10, p)
        self.assertEqual(ids(r), ["A", "C"])                        # A+B = 8 > 0.5 × 10 in ward x
        self.assertIn("ward", r["binding"])

    def test_existing_counts_in_concentration(self):
        p = InvestorProfile(**{**LOOSE.__dict__, "max_ward_share": 0.5})
        r = allocate([cand("A", 4, 3, ward="x")], 10, p, existing=[{"ward": "x", "ptype": "land", "value": 10}])
        self.assertEqual(ids(r), [])                                # 10 + 4 > 0.5 × 20
        r = allocate([cand("A", 4, 3, ward="y")], 10, p, existing=[{"ward": "x", "ptype": "land", "value": 10}])
        self.assertEqual(ids(r), ["A"])

    def test_risk_budget(self):
        p = InvestorProfile(**{**LOOSE.__dict__, "risk_budget_share": 0.3})
        r = allocate([cand("A", 3, 5, bear=2), cand("B", 3, 4, bear=2), cand("C", 3, 1, bear=0.5)], 10, p)
        self.assertEqual(ids(r), ["A", "C"])                        # bear cap 3: A+B = 4 too much
        self.assertEqual(r["binding"], ["risk"])

    def test_liquidity_floor_non_monotone(self):
        p = InvestorProfile(**{**LOOSE.__dict__, "max_avg_exit_months": 8})
        # A alone averages 12 (> 8); A + B averages (4·12 + 4·3)/8 = 7.5 — feasible only together
        r = allocate([cand("A", 4, 5, liq=12), cand("B", 4, 1, liq=3)], 10, p)
        self.assertEqual(ids(r), ["A", "B"])

    def test_asset_exclusive(self):
        r = allocate([cand("h", 3, 5, asset="lot1"), cand("f", 3, 4, asset="lot1"), cand("o", 3, 1)], 10, LOOSE)
        self.assertEqual(ids(r), ["h", "o"])
        self.assertEqual(r["binding"], ["asset"])

    def test_set_aside(self):
        p = InvestorProfile(**{**LOOSE.__dict__, "max_single_asset_share": 0.5})
        bad = {"id": "m", "strategy": "buy_hold"}
        flip = {**cand("f", 1, 1), "strategy": "fix_flip"}
        cons = InvestorProfile(**{**p.__dict__, "risk_tolerance": "conservative"})
        r = allocate([cand("big", 6, 9), cand("neg", 1, -1), bad, flip, cand("ok", 2, 1)], 10, cons)
        reasons = {a["id"]: a["reason"] for a in r["set_aside"]}
        self.assertIn("single_asset", reasons["big"])
        self.assertIn("≤ 0", reasons["neg"])
        self.assertIn("missing", reasons["m"])
        self.assertIn("profile", reasons["f"])
        self.assertEqual(ids(r), ["ok"])

    def test_needs_reserve_basis(self):
        self.assertIsInstance(allocate([cand("A", 1, 1)], 10, InvestorProfile()), Insufficient)
        r = allocate([cand("A", 1, 1)], 10, InvestorProfile(time_available="active"), reserve=0.0)
        self.assertEqual(ids(r), ["A"])


class Greedy(unittest.TestCase):
    def test_many_candidates(self):
        cs = [cand(f"c{i:02d}", 1, 1 + i / 100) for i in range(20)]
        r = allocate(cs, 5, LOOSE)
        self.assertEqual(r["method"], "greedy+repair")
        self.assertEqual(len(r["chosen"]), 5)
        self.assertEqual(ids(r), [f"c{i}" for i in range(15, 20)])

    def test_repair_swaps(self):
        # ratio picks A (1.0) then cannot fit B; a swap A→B raises EV 3 → 9
        cs = [cand("A", 3, 3), cand("B", 9, 9)] + [cand(f"z{i:02d}", 10, 0.1) for i in range(18)]
        r = allocate(cs, 10, LOOSE)
        self.assertEqual(r["method"], "greedy+repair")
        self.assertEqual(ids(r), ["B"])


class FromEvaluation(unittest.TestCase):
    def test_pipeline(self):
        ev = evaluate_all(OPP, FULL)
        cs = candidates_from_evaluation(ev, "lot1", "w1", "house")
        self.assertEqual(len(cs), len(ev["ranked"]))
        r = allocate(cs, 5e9, LOOSE)
        self.assertLessEqual(len(r["chosen"]), 1)                   # one asset → at most one strategy
        if r["chosen"]:
            best = max((c for c in cs if c["ev_npv"] > 0 and c["peak_cash"] <= 5e9), key=lambda c: c["ev_npv"])
            self.assertEqual(r["chosen"][0]["id"], best["id"])


if __name__ == "__main__":
    unittest.main()
