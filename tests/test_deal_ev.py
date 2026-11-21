"""Scenario EV: overrides, weighting, probability checks, kill triggers, default set."""
import unittest
from dataclasses import replace

from vnrealty.deal.engine import Deal, analyse, irr_monthly
from vnrealty.deal.ev import apply_overrides, default_scenarios, equity_flows, ev, kill_triggers

D = Deal()


class Overrides(unittest.TestCase):
    def test_absolute_multiplier_and_add(self):
        d = apply_overrides(D, {"vacancy": 0.2, "rent": {"x": 0.5}, "float_rate": {"add": 0.03}})
        self.assertEqual(d.vacancy, 0.2)
        self.assertAlmostEqual(d.rent, D.rent * 0.5)
        self.assertAlmostEqual(d.float_rate, D.float_rate + 0.03)

    def test_int_fields_stay_int(self):
        d = apply_overrides(D, {"hold_years": {"x": 1.26}})
        self.assertIsInstance(d.hold_years, int)
        self.assertEqual(d.hold_years, 13)

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            apply_overrides(D, {"rnet": 1})
        with self.assertRaises(ValueError):
            apply_overrides(D, {"rent": {"times": 2}})


class EV(unittest.TestCase):
    def test_equity_flows_sum_to_engine_profit(self):
        self.assertAlmostEqual(sum(equity_flows(D)), analyse(D)["profit"], delta=1.0)

    def test_probabilities_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            ev(D, [{"name": "a", "p": 0.5, "overrides": {}}, {"name": "b", "p": 0.4, "overrides": {}}])
        with self.assertRaises(ValueError):
            ev(D, [{"name": "a", "p": 1.2, "overrides": {}}, {"name": "b", "p": -0.2, "overrides": {}}])

    def test_single_certain_scenario_equals_analyse(self):
        r = ev(D, [{"name": "base", "p": 1.0, "overrides": {}}])
        a = analyse(D)
        self.assertAlmostEqual(r["expected_npv"], a["npv"])
        self.assertAlmostEqual(r["irr_weighted"], a["irr"])
        self.assertAlmostEqual(r["irr_of_expected_flows"], a["irr"], places=6)

    def test_weighting_and_tails(self):
        sc = [{"name": "good", "p": 0.7, "overrides": {}},
              {"name": "bad", "p": 0.3, "overrides": {"rent": {"x": 0.2}, "price_growth": -0.05}}]
        r = ev(D, sc)
        good, bad = analyse(D), analyse(apply_overrides(D, sc[1]["overrides"]))
        self.assertAlmostEqual(r["expected_profit"], 0.7 * good["profit"] + 0.3 * bad["profit"])
        self.assertLess(bad["profit"], 0)
        self.assertAlmostEqual(r["p_loss"], 0.3)
        self.assertEqual(r["worst"]["name"], "bad")
        self.assertGreaterEqual(r["p_irr_below_hurdle"], 0.3)
        # IRR of the averaged flows is its own number, not the average IRR
        flows = [0.7 * a + 0.3 * b for a, b in zip(equity_flows(D), equity_flows(apply_overrides(D, sc[1]["overrides"])))]
        self.assertAlmostEqual(r["irr_of_expected_flows"], irr_monthly(flows))

    def test_default_scenarios_sum_to_one_and_are_judgement(self):
        sc = default_scenarios(D)
        self.assertAlmostEqual(sum(s["p"] for s in sc), 1.0)
        self.assertTrue(all(s["judgement"] for s in sc))
        r = ev(D, sc)
        self.assertEqual(len(r["scenarios"]), 5)


class Kill(unittest.TestCase):
    def test_fired_triggers_carry_numbers(self):
        a = analyse(D)
        fired = kill_triggers(a, {"dscr_lt": 5.0, "irr_lt": 0.0, "peak_cash_gt": 1.0})
        rules = {f["rule"]: f for f in fired}
        self.assertIn("dscr_lt", rules)
        self.assertNotIn("irr_lt", rules)
        self.assertAlmostEqual(rules["peak_cash_gt"]["value"], a["peak_cash_out"])

    def test_no_debt_dscr_does_not_fire_but_missing_irr_does(self):
        a = analyse(replace(D, loan=0.0))
        self.assertEqual(kill_triggers(a, {"dscr_lt": 1.2}), [])
        a2 = dict(a, irr=None)
        f = kill_triggers(a2, {"irr_lt": 0.08})
        self.assertEqual(len(f), 1)
        self.assertIsNone(f[0]["value"])

    def test_unknown_rule_raises(self):
        with self.assertRaises(ValueError):
            kill_triggers(analyse(D), {"dscr_below": 1})

    def test_p_loss_rule_on_ev_result(self):
        r = ev(D, [{"name": "x", "p": 1.0, "overrides": {"rent": 0.0, "price_growth": -0.1}}])
        self.assertEqual(kill_triggers(r, {"p_loss_gt": 0.2})[0]["value"], 1.0)


if __name__ == "__main__":
    unittest.main()
