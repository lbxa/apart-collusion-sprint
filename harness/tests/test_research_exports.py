"""Research exports retain history and represent undefined rates explicitly."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from experiments.runner import ExperimentRunner
from experiments.treatments import CoalitionDef, TreatmentConfig
from game_api.mock import MockGameAPI
from game_api.types import Scenario
from run_knockout import run_conditions


class ResearchExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_exported_history_analysis_compares_stable_role_slots(self):
        treatment = TreatmentConfig("history", "History", "Two distinct episodes",
            jury_size=3, num_episodes=2, deliberation_rounds=1,
            use_scripted_creator=True, use_scripted_challenger=True,
            scripted_juror_indices=[0, 1, 2], scripted_juror_type="adversarial",
            coalitions=[CoalitionDef("c", ["juror_0", "juror_1"], "Support creator")])
        with tempfile.TemporaryDirectory() as directory:
            await ExperimentRunner(MockGameAPI(), directory).run_experiment(
                treatment, [Scenario("s", "Claim", "For", "Against", False)], "history")
            lines = (Path(directory) / "history/episodes.jsonl").read_text().splitlines()
            second = json.loads(lines[1])
        signals = second["collusion_analysis"]["signals"]
        cross_episode = next(signal for signal in signals if signal["type"] == "cross_episode_consistency")
        self.assertGreater(cross_episode["score"], 0)

    async def test_cli_renders_undefined_rates_without_invalid_json_or_crashing(self):
        metrics = Mock()
        metrics.summary.return_value = {"total_episodes": 1, "false_verdict_rate": None,
                                       "verdict_accuracy": None, "hung_jury_rate": 1.0}
        runner = Mock()
        runner.run_experiment = AsyncMock(return_value=metrics)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, \
             patch("run_knockout.ExperimentRunner", return_value=runner), \
             contextlib.redirect_stdout(output):
            await run_conditions({"x": TreatmentConfig("x", "X", "Unknown truth")},
                                 Path(directory), use_core_engine=False)
            text = (Path(directory) / "knockout_results.json").read_text()
        self.assertIn("n/a", output.getvalue())
        self.assertNotIn("NaN", text)
