"""evaluate_all: one EV basis across strategies, explicit score, exclusions, kill-trigger demotion."""
import unittest

from vnrealty.deal.ev import default_scenarios, ev
from vnrealty.strategy import catalog as C
from vnrealty.strategy.evaluate import default_weights, ev_strategy, evaluate_all, scenarios_for, score
from vnrealty.strategy.profile import InvestorProfile
from tests.strategy_fixtures import FULL, OPP


class EvParity(unittest.TestCase):
    def test_plain_deal_equals_deal_ev(self):
        sd = C.build("buy_hold", OPP, {**FULL, "loan_ltv": 0.5, "mortgage_rate": 0.10})
        sc = default_scenarios(sd.deal)
        a, b = ev_strategy(sd, sc), ev(sd.deal, sc)
        self.assertAlmostEqual(a["expected_npv"], b["expected_npv"], delta=1)
        self.assertAlmostEqual(a["expected_profit"], b["expected_profit"], delta=1)
        self.assertAlmostEqual(a["p_loss"], b["p_loss"])
        self.assertAlmostEqual(a["irr_of_expected_flows"], b["irr_of_expected_flows"], places=9)
        self.assertEqual(a["worst"]["name"], b["worst"]["name"])

    def test_bad_probabilities_raise(self):
        sd = C.build("buy_hold", OPP, FULL)
        with self.assertRaises(ValueError):
            ev_strategy(sd, [{"name": "a", "p": 0.5, "overrides": {}}])

    def test_bear_override_for_resale_strategies(self):
        sd = C.build("fix_flip", OPP, FULL)
        bear = next(s for s in scenarios_for(sd) if s["name"] == "bear")
        self.assertEqual(bear["overrides"]["value_after"], {"x": 0.9})
        hold = next(s for s in scenarios_for(C.build("buy_hold", OPP, FULL)) if s["name"] == "bear")
        self.assertNotIn("value_after", hold["overrides"])


class Score(unittest.TestCase):
    def test_hand_checked(self):
        w = {"w_eff": 1.0, "w_bear": 0.5, "w_ploss": 0.25, "w_liq": 0.02, "w_cx": 0.05}
        s = score(200.0, 1000.0, -100.0, 0.2, 6, 3, w)
        self.assertAlmostEqual(s["score"], 0.2 - 0.05 - 0.05 - 0.01 - 0.025)
        self.assertAlmostEqual(score(200.0, 1000.0, 50.0, 0, 0, 1, w)["score"], 0.2)   # bear gain is no penalty


class EvaluateAll(unittest.TestCase):
    def test_ranks_every_strategy(self):
        r = evaluate_all(OPP, FULL)
        self.assertEqual(len(r["ranked"]) + len(r["excluded"]), len(C.STRATEGIES))
        clean = [x for x in r["ranked"] if not x["kill"]]
        self.assertEqual([x["score"] for x in clean], sorted((x["score"] for x in clean), reverse=True))
        seen_killed = False
        for x in r["ranked"]:
            seen_killed |= bool(x["kill"])
            if seen_killed:
                self.assertTrue(x["kill"], "a clean strategy ranked below a killed one")
        for x in r["ranked"]:
            self.assertAlmostEqual(x["score"], sum(x["terms"].values()))
            self.assertGreaterEqual(x["peak_cash"], x["metrics"]["peak_cash"])
        self.assertEqual(r["weights"], default_weights())

    def test_score_recomputes(self):
        r = evaluate_all(OPP, FULL, strategies=["buy_hold"])
        x = r["ranked"][0]
        s = score(x["ev"]["expected_npv"], x["peak_cash"], x["ev"]["bear"]["npv"], x["ev"]["p_loss"],
                  C.liquidity_months("buy_hold"), C.complexity("buy_hold"), default_weights())
        self.assertAlmostEqual(x["score"], s["score"])

    def test_insufficient_excluded_with_reason(self):
        a = dict(FULL)
        del a["after_repair_value"]
        r = evaluate_all(OPP, a, strategies=["fix_flip", "buy_hold"])
        self.assertEqual([e["strategy"] for e in r["excluded"]], ["fix_flip"])
        self.assertIn("after_repair_value", r["excluded"][0]["reason"])

    def test_profile_excludes_and_hurdle(self):
        p = InvestorProfile(risk_tolerance="conservative", time_available="active", hurdle=0.12)
        r = evaluate_all(OPP, {k: v for k, v in FULL.items() if k != "hurdle"}, profile=p)
        ex = {e["strategy"]: e["reason"] for e in r["excluded"]}
        for s in ("fix_flip", "rental_arbitrage", "subdivide"):
            self.assertIn("profile", ex[s])
        self.assertEqual(r["hurdle"], 0.12)
        self.assertEqual(r["weights"]["w_bear"], 1.0)

    def test_profile_ltv_and_horizon(self):
        p = InvestorProfile(risk_tolerance="aggressive", time_available="active", max_ltv=0.3, horizon_years=2)
        r = evaluate_all(OPP, {**FULL, "loan_ltv": 0.5, "mortgage_rate": 0.1}, profile=p,
                         strategies=["buy_hold", "fix_flip", "subdivide"])
        ex = {e["strategy"]: e["reason"] for e in r["excluded"]}
        self.assertIn("LTV", ex["buy_hold"])
        self.assertIn("LTV", ex["fix_flip"])
        r = evaluate_all(OPP, FULL, profile=p, strategies=["buy_hold", "fix_flip"])
        ex = {e["strategy"]: e["reason"] for e in r["excluded"]}
        self.assertIn("horizon", ex["buy_hold"])
        self.assertEqual([x["strategy"] for x in r["ranked"]], ["fix_flip"])

    def test_weights_override(self):
        r = evaluate_all(OPP, FULL, strategies=["land_bank"], weights={"w_liq": 1.0})
        self.assertAlmostEqual(r["ranked"][0]["terms"]["liquidity_penalty"], -1.0)

    def test_custom_scenarios(self):
        sc = [{"name": "only", "p": 1.0, "overrides": {}}]
        r = evaluate_all(OPP, FULL, strategies=["buy_hold"], scenarios=sc)
        x = r["ranked"][0]
        self.assertAlmostEqual(x["ev"]["expected_npv"], x["metrics"]["npv"])


if __name__ == "__main__":
    unittest.main()
