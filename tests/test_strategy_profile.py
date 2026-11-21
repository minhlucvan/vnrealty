"""Investor profile: presets, eligibility rules, explicit allow-list, questionnaire."""
import unittest

from vnrealty.strategy.profile import (PRESETS, QUESTIONS, InvestorProfile, profile_constraints, profile_from_answers,
                                       reserve_cash)


class Constraints(unittest.TestCase):
    def test_conservative_excludes_flip_and_arbitrage(self):
        c = profile_constraints(InvestorProfile(risk_tolerance="conservative", time_available="active"))
        for s in ("fix_flip", "rental_arbitrage", "subdivide"):
            self.assertIn(s, c["excluded"])
        self.assertIn("buy_to_homestay", c["allowed"])
        self.assertEqual(c["max_ltv"], PRESETS["conservative"]["max_ltv"])

    def test_time_rules(self):
        passive = profile_constraints(InvestorProfile(time_available="passive"))
        self.assertIn("buy_to_chdv", passive["excluded"])
        self.assertIn("buy_hold", passive["allowed"])
        part = profile_constraints(InvestorProfile(time_available="part_time"))
        self.assertIn("buy_to_homestay", part["excluded"])
        self.assertIn("buy_to_chdv", part["allowed"])
        active = profile_constraints(InvestorProfile(time_available="active"))
        self.assertEqual(active["excluded"], {})

    def test_allowed_list_overrides(self):
        c = profile_constraints(InvestorProfile(risk_tolerance="conservative", time_available="passive",
                                                strategies_allowed=("fix_flip", "buy_hold")))
        self.assertEqual(c["allowed"], ["buy_hold", "fix_flip"])
        with self.assertRaises(ValueError):
            profile_constraints(InvestorProfile(strategies_allowed=("moon",)))

    def test_explicit_fields_win_and_bad_values_raise(self):
        c = profile_constraints(InvestorProfile(max_ltv=0.2, horizon_years=3))
        self.assertEqual(c["max_ltv"], 0.2)
        self.assertEqual(c["max_hold_months"], 36)
        with self.assertRaises(ValueError):
            profile_constraints(InvestorProfile(risk_tolerance="yolo"))
        with self.assertRaises(ValueError):
            profile_constraints(InvestorProfile(time_available="never"))

    def test_reserve(self):
        self.assertIsNone(reserve_cash(InvestorProfile()))
        self.assertEqual(reserve_cash(InvestorProfile(monthly_outgoings=20e6, min_liquidity_months=6)), 120e6)
        self.assertEqual(reserve_cash(InvestorProfile(risk_tolerance="conservative", monthly_outgoings=10e6)), 120e6)


class Questionnaire(unittest.TestCase):
    def test_answers_build_profile(self):
        p = profile_from_answers({"risk": "aggressive", "time": "active", "horizon": 5, "leverage": 0.5,
                                  "hurdle": 0.12, "reserve": 3, "outgoings": 25e6})
        self.assertEqual((p.risk_tolerance, p.time_available, p.horizon_years, p.max_ltv, p.hurdle,
                          p.min_liquidity_months, p.monthly_outgoings), ("aggressive", "active", 5, 0.5, 0.12, 3, 25e6))

    def test_every_question_maps_to_a_field(self):
        fields = set(InvestorProfile.__dataclass_fields__)
        for q in QUESTIONS:
            self.assertIn(q["field"], fields)

    def test_bad_answers(self):
        with self.assertRaises(ValueError):
            profile_from_answers({"risk": "reckless"})
        with self.assertRaises(ValueError):
            profile_from_answers({"nope": 1})
        with self.assertRaises(ValueError):
            profile_from_answers({"outgoings": -1})


if __name__ == "__main__":
    unittest.main()
