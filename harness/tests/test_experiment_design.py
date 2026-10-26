"""Experiment cells map to treatments exactly as docs/experiment-design.md defines them."""

import argparse
import unittest

import run_experiments
from experiments.design import Cell, scenarios_for, treatment_for
from experiments.knockout import FICTIONAL_SCENARIOS_AMBIGUOUS, FICTIONAL_SCENARIOS_CLEAR
from game_api.core_engine import CoreEngineAPI
from game_api.types import EpisodeConfig

EXPERIMENT_1 = "M1-C1-T1-R1-S1-E1"


class CellTests(unittest.TestCase):
    def test_ids_round_trip_and_all_64_cells_are_distinct(self):
        cells = [Cell.parse(f"M{m}-C{c}-T{t}-R{r}-S{s}-E{e}")
                 for m in (0, 1) for c in (0, 1) for t in (0, 1)
                 for r in (0, 1) for s in (0, 1) for e in (0, 1)]
        self.assertEqual(len({cell.id for cell in cells}), 64)
        self.assertTrue(all(Cell.parse(cell.id) == cell for cell in cells))

    def test_malformed_ids_are_rejected(self):
        for text in ("", "M1-C1", "M2-C1-T1-R1-S1-E1", "C1-M1-T1-R1-S1-E1", "m1-c1-t1-r1-s1-e1x"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Cell.parse(text)

    def test_experiment_one_is_every_lever_on(self):
        treatment = treatment_for(Cell.parse(EXPERIMENT_1))
        self.assertEqual(treatment.treatment_id, "exp_m1c1t1r1s1e1")
        self.assertEqual((treatment.jury_size, treatment.deliberation_rounds, treatment.num_episodes), (7, 3, 10))
        self.assertEqual((treatment.payout.creator_bet, treatment.payout.challenger_bet, treatment.payout.juror_bond),
                         (10.0, 10.0, 1.0))
        self.assertEqual(treatment.pay_multiplier, 1.2)
        self.assertTrue(treatment.transfers_enabled)
        self.assertTrue(treatment.private_chat)
        self.assertTrue(treatment.memory_enabled)
        self.assertEqual(treatment.memory_window, 10)
        self.assertTrue(treatment.public_messaging)
        self.assertEqual(treatment.bribes, [])
        self.assertEqual(treatment.juror_overrides, {})
        self.assertIsNone(treatment.juror_motivation)

    def test_each_off_level_changes_only_its_own_parameters(self):
        base = treatment_for(Cell.parse(EXPERIMENT_1))
        off = treatment_for(Cell.parse("M0-C0-T0-R0-S0-E0"))
        self.assertEqual(off.pay_multiplier, 1.0)
        self.assertFalse(off.private_chat)
        self.assertIs(off.transfers_enabled, False)
        self.assertFalse(off.memory_enabled)
        self.assertEqual(off.memory_window, 0)
        self.assertEqual((off.payout.creator_bet, off.payout.challenger_bet, off.payout.juror_bond), (1.0, 1.0, 0.10))
        for field in ("jury_size", "deliberation_rounds", "num_episodes", "seed", "public_messaging"):
            self.assertEqual(getattr(off, field), getattr(base, field), field)

    def test_evidence_levels_select_ten_balanced_scenarios(self):
        for name, scenarios in [("ambiguous", FICTIONAL_SCENARIOS_AMBIGUOUS), ("clear", FICTIONAL_SCENARIOS_CLEAR)]:
            with self.subTest(evidence=name):
                self.assertEqual(len(scenarios), 10)
                self.assertEqual(sum(s.ground_truth is True for s in scenarios), 5)
                self.assertEqual(len({s.scenario_id for s in scenarios}), 10)
        self.assertIs(scenarios_for(Cell.parse("M1-C1-T1-R1-S1-E1")), FICTIONAL_SCENARIOS_AMBIGUOUS)
        self.assertIs(scenarios_for(Cell.parse("M1-C1-T1-R1-S1-E0")), FICTIONAL_SCENARIOS_CLEAR)


class CellSelectionTests(unittest.TestCase):
    def test_every_advertised_treatment_is_representable_by_the_real_engine(self):
        for key, treatment in run_experiments.PREDEFINED_TREATMENTS.items():
            with self.subTest(treatment=key):
                self.assertIn(treatment.jury_size, (3, 5, 7))
                CoreEngineAPI.validate_config(EpisodeConfig(
                    episode_id="catalog-preflight", jury_size=treatment.jury_size,
                    payout=treatment.payout,
                ))

    def args(self, **overrides):
        values = dict(all=False, compare_jury_sizes=False, compare_incentives=False, treatment=None,
                      cell=EXPERIMENT_1, blocks=2, episodes=None, scripted=False, seed=7, model=None,
                      cot_monitor=None)
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_a_cell_runs_as_independent_blocks_with_the_requested_seed(self):
        treatments, scenarios = run_experiments.select_treatments(self.args())
        self.assertEqual(list(treatments), [f"{EXPERIMENT_1}_b1", f"{EXPERIMENT_1}_b2"])
        self.assertTrue(all(t.num_episodes == 10 and t.seed == 7 for t in treatments.values()))
        self.assertIs(scenarios, FICTIONAL_SCENARIOS_AMBIGUOUS)

    def test_the_episode_override_sets_the_block_length(self):
        treatments, _ = run_experiments.select_treatments(self.args(episodes=4, blocks=1))
        self.assertEqual([t.num_episodes for t in treatments.values()], [4])


if __name__ == "__main__":
    unittest.main()
