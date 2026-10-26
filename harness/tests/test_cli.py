"""CLI contracts without starting model clients or spending API credits."""

import asyncio
import contextlib
import io
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import run_experiments
import run_knockout
from experiments.design import LINEUPS
import run_demo
from agents.scripted import AdversarialAgent, HonestAgent
from experiments.runner import ExperimentRunner


def metrics(failure_rate=0.0):
    return SimpleNamespace(summary=lambda: {
        "total_episodes": 2,
        "false_verdict_rate": 0.0,
        "verdict_accuracy": 1.0,
        "hung_jury_rate": 0.0,
        "infrastructure_failure_rate": failure_rate,
    })


class EntryPointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, previous)

    async def invoke(self, module, arguments, *, failure_rate=0.0, runner_error=None,
                     startup_error=None, validation_error=None):
        engine = SimpleNamespace(
            backend="core", start=AsyncMock(side_effect=startup_error), stop=AsyncMock(),
        )
        core_factory = Mock(return_value=engine)
        core_factory.validate_config = Mock(side_effect=validation_error)
        runner = Mock()
        runner.run_experiment = AsyncMock(return_value=metrics(failure_rate), side_effect=runner_error)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(module, "CoreEngineAPI", core_factory, create=True), \
             patch.object(module, "ExperimentRunner", return_value=runner), \
             patch.object(sys, "argv", [module.__file__, *arguments, "--output", directory]), \
             patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-never-sent"}, clear=True), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = await module.main()
            output_exists = any(Path(directory).glob("*results.json"))
        return SimpleNamespace(result=result, engine=engine, core=core_factory,
                               runner=runner, output_exists=output_exists)

    async def test_knockout_dry_run_defaults_to_real_engine_and_honors_episode_override(self):
        run = await self.invoke(run_knockout, ["--condition", "knockout_full", "--dry-run", "--episodes", "2"])
        self.assertEqual(run.result, 0)
        run.core.assert_called_once_with(core_engine_dir=None)
        run.engine.start.assert_awaited_once()
        run.engine.stop.assert_awaited_once()
        treatment = run.runner.run_experiment.await_args.args[0]
        self.assertEqual(treatment.num_episodes, 2)
        self.assertTrue(treatment.use_scripted_creator)
        self.assertTrue(treatment.use_scripted_challenger)
        self.assertEqual(treatment.scripted_juror_indices, list(range(treatment.jury_size)))

    async def test_experiments_scripted_defaults_to_real_engine(self):
        run = await self.invoke(run_experiments, ["--treatment", "baseline", "--scripted", "--episodes", "2"])
        self.assertEqual(run.result, 0)
        run.core.assert_called_once_with(core_engine_dir=None)
        run.engine.start.assert_awaited_once()
        run.engine.stop.assert_awaited_once()
        treatment = run.runner.run_experiment.await_args.args[0]
        self.assertEqual(treatment.num_episodes, 2)
        self.assertTrue(treatment.use_scripted_creator)
        self.assertEqual(treatment.scripted_juror_indices, list(range(treatment.jury_size)))

    async def test_wandb_is_opt_in_and_cell_blocks_share_one_group(self):
        tracker = Mock()
        context = Mock(__enter__=Mock(return_value=tracker), __exit__=Mock(return_value=False))
        with patch.object(run_experiments, "WandbTracker", return_value=context) as factory:
            local = await self.invoke(run_experiments, ["--cell", "M0-C0-T0-R0-S0-E0", "--blocks", "1", "--scripted"])
            self.assertEqual(local.result, 0)
            factory.assert_not_called()
            remote = await self.invoke(run_experiments, [
                "--cell", "M0-C0-T0-R0-S0-E0", "--blocks", "2", "--episodes", "2", "--scripted",
                "--wandb", "--wandb-project", "test-project", "--run-purpose", "smoke",
            ])
            self.assertEqual(remote.result, 0)
            self.assertEqual(factory.call_count, 2)
            calls = [call.kwargs for call in factory.call_args_list]
            self.assertEqual(calls[0]["group"], calls[1]["group"])
            self.assertEqual(calls[0]["project"], "test-project")
            self.assertEqual(calls[0]["purpose"], "smoke")
            self.assertEqual(calls[0]["backend"], "core")
            self.assertEqual([call["blocks"] for call in calls], [2, 2])
            self.assertEqual([call["block_index"] for call in calls], [1, 2])
            self.assertEqual(len(calls[0]["scenario_ids"]), 2)
            self.assertEqual(tracker.record_results.call_count, 2)

    async def test_wandb_treatment_comparisons_are_not_labeled_as_blocks(self):
        context = Mock(__enter__=Mock(return_value=Mock()), __exit__=Mock(return_value=False))
        with patch.object(run_experiments, "WandbTracker", return_value=context) as factory:
            remote = await self.invoke(run_experiments, [
                "--all", "--episodes", "2", "--scripted", "--wandb",
                "--wandb-project", "test-project",
            ])
            self.assertEqual(remote.result, 0)
            self.assertEqual(factory.call_count, 4)
            for call in factory.call_args_list:
                self.assertIsNone(call.kwargs["blocks"])
                self.assertIsNone(call.kwargs["block_index"])

    async def test_model_override_applies_to_all_live_roles_without_changing_factors(self):
        original = run_experiments.PREDEFINED_TREATMENTS["baseline"].creator_model
        run = await self.invoke(run_experiments, [
            "--cell", "M0-C0-T0-R0-S0-E0", "--blocks", "1", "--episodes", "2",
            "--model", "test/paid-model", "--live",
        ])
        self.assertEqual(run.result, 0)
        treatment = run.runner.run_experiment.await_args.args[0]
        for role in ("creator", "challenger", "juror"):
            self.assertEqual(getattr(treatment, f"{role}_model"), "test/paid-model")
            self.assertEqual(getattr(treatment, f"{role}_provider"), "openrouter")
        self.assertEqual(treatment.pay_multiplier, 1.0)
        self.assertIs(treatment.transfers_enabled, False)
        self.assertFalse(treatment.private_chat)
        self.assertFalse(treatment.memory_enabled)
        self.assertFalse(treatment.use_scripted_creator)
        self.assertFalse(treatment.use_scripted_challenger)
        self.assertEqual(treatment.scripted_juror_indices, [])
        self.assertEqual(run_experiments.PREDEFINED_TREATMENTS["baseline"].creator_model, original)

    async def test_wandb_labels_each_lineup_run_with_its_block(self):
        first, second = list(LINEUPS)[:2]
        context = Mock(__enter__=Mock(return_value=Mock()), __exit__=Mock(return_value=False))
        with patch.object(run_experiments, "WandbTracker", return_value=context) as factory:
            run = await self.invoke(run_experiments, [
                "--cell", "M0-C0-T0-R0-S0-E0", "--blocks", "2", "--episodes", "1", "--lineup", first, second,
                "--live", "--wandb", "--wandb-project", "test-project",
            ])
        self.assertEqual(run.result, 0)
        calls = [call.kwargs for call in factory.call_args_list]
        self.assertEqual([call["name"] for call in calls], [f"M0-C0-T0-R0-S0-E0_{name}_b{block}"
                                                            for block in (1, 2) for name in (first, second)])
        self.assertEqual([call["block_index"] for call in calls], [1, 1, 2, 2])
        self.assertEqual({call["blocks"] for call in calls}, {2})
        self.assertEqual(len({call["group"] for call in calls}), 1)

    async def test_lineup_needs_a_cell_and_excludes_a_single_model(self):
        name = next(iter(LINEUPS))
        for arguments, message in [
            (["--treatment", "baseline", "--lineup", name], "--lineup requires --cell"),
            (["--cell", "M0-C0-T0-R0-S0-E0", "--lineup", name, "--model", "test/model"], "not allowed with"),
            (["--cell", "M0-C0-T0-R0-S0-E0", "--lineup", "unknown"], "invalid choice"),
        ]:
            with self.subTest(arguments=arguments):
                errors = io.StringIO()
                with patch.object(run_experiments, "CoreEngineAPI") as core, \
                     patch.object(sys, "argv", [run_experiments.__file__, *arguments]), \
                     contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
                    await run_experiments.main()
                core.assert_not_called()
                self.assertIn(message, errors.getvalue())

    async def test_blank_model_is_rejected_before_engine_startup(self):
        errors = io.StringIO()
        with patch.object(run_experiments, "CoreEngineAPI") as core, \
             patch.object(sys, "argv", [run_experiments.__file__, "--cell", "M0-C0-T0-R0-S0-E0", "--model", "  "]), \
             contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
            await run_experiments.main()
        core.assert_not_called()
        self.assertIn("--model must not be blank", errors.getvalue())

    async def test_removed_mock_mode_is_rejected_before_engine_startup(self):
        for module, selector in [(run_knockout, ["--condition", "knockout_full"]),
                                 (run_experiments, ["--treatment", "baseline"])]:
            with self.subTest(module=module.__name__):
                errors = io.StringIO()
                with patch.object(module, "CoreEngineAPI") as core, \
                     patch.object(sys, "argv", [module.__file__, *selector, "--mock", "--dry-run"]), \
                     contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                    await module.main()
                self.assertEqual(raised.exception.code, 2)
                core.assert_not_called()
                self.assertIn("unrecognized arguments: --mock", errors.getvalue())

    async def test_explicit_core_engine_flag_and_directory_override_remain_supported(self):
        for module, selector in [(run_knockout, ["--condition", "knockout_full"]),
                                 (run_experiments, ["--treatment", "baseline"])]:
            with self.subTest(module=module.__name__):
                run = await self.invoke(module, [*selector, "--core-engine", "--core-engine-dir", "/tmp/test-engine", "--scripted", "--episodes", "1"])
                self.assertEqual(run.result, 0)
                run.core.assert_called_once_with(core_engine_dir="/tmp/test-engine")

    async def test_engine_stops_on_experiment_error_and_cancellation(self):
        for error in [RuntimeError("experiment failed"), asyncio.CancelledError()]:
            for module, selector in [(run_knockout, ["--condition", "knockout_full"]),
                                     (run_experiments, ["--treatment", "baseline"])]:
                with self.subTest(module=module.__name__, error=type(error).__name__):
                    engine = SimpleNamespace(backend="core", start=AsyncMock(), stop=AsyncMock())
                    core_factory = Mock(return_value=engine)
                    core_factory.validate_config = Mock()
                    runner = Mock(run_experiment=AsyncMock(side_effect=error))
                    with tempfile.TemporaryDirectory() as directory, \
                         patch.object(module, "CoreEngineAPI", core_factory, create=True), \
                         patch.object(module, "ExperimentRunner", return_value=runner), \
                         patch.object(sys, "argv", [module.__file__, *selector, "--dry-run", "--output", directory]), \
                         contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        if isinstance(error, asyncio.CancelledError):
                            with self.assertRaises(asyncio.CancelledError):
                                await module.main()
                        else:
                            self.assertEqual(await module.main(), 1)
                    engine.stop.assert_awaited_once()

    async def test_failed_engine_start_is_cleaned_up_without_mock_fallback(self):
        for module, selector in [(run_knockout, ["--condition", "knockout_full"]),
                                 (run_experiments, ["--treatment", "baseline"])]:
            with self.subTest(module=module.__name__):
                run = await self.invoke(module, [*selector, "--dry-run"], startup_error=RuntimeError("binary unavailable"))
                self.assertEqual(run.result, 1)
                run.engine.stop.assert_awaited_once()
                run.runner.run_experiment.assert_not_awaited()

    async def test_preflight_failure_is_visible_before_engine_startup(self):
        run = await self.invoke(run_experiments, ["--treatment", "baseline", "--scripted"],
                                validation_error=ValueError("unsupported jury size"))
        self.assertEqual(run.result, 1)
        run.core.assert_not_called()
        run.runner.run_experiment.assert_not_awaited()

    async def test_jury_comparison_uses_only_supported_core_sizes(self):
        run = await self.invoke(run_experiments, ["--compare-jury-sizes", "--scripted", "--episodes", "1"])
        self.assertEqual(run.result, 0)
        treatments = [call.args[0] for call in run.runner.run_experiment.await_args_list]
        self.assertEqual([t.jury_size for t in treatments], [3, 3, 5, 5, 7, 7])
        self.assertTrue(all(t.scripted_juror_indices == list(range(t.jury_size)) for t in treatments))

    async def test_infrastructure_failures_are_saved_but_return_nonzero(self):
        for module, selector in [(run_knockout, ["--condition", "knockout_full"]),
                                 (run_experiments, ["--treatment", "baseline"])]:
            with self.subTest(module=module.__name__):
                run = await self.invoke(module, [*selector, "--dry-run"], failure_rate=0.5)
                self.assertEqual(run.result, 1)
                self.assertTrue(run.output_exists)
                run.engine.stop.assert_awaited_once()

    async def test_live_option_uses_the_configured_models_instead_of_scripting(self):
        run = await self.invoke(run_experiments, ["--treatment", "baseline", "--live", "--episodes", "1"])
        self.assertEqual(run.result, 0)
        treatment = run.runner.run_experiment.await_args.args[0]
        self.assertFalse(treatment.use_scripted_creator)
        self.assertEqual(treatment.scripted_juror_indices, [])

    async def test_scripted_shorthand_still_starts_the_core_backend(self):
        for module in (run_knockout, run_experiments):
            with self.subTest(module=module.__name__):
                run = await self.invoke(module, ["--dry-run", "--episodes", "1"])
                self.assertEqual(run.result, 0)
                run.core.assert_called_once_with(core_engine_dir=None)
                run.engine.start.assert_awaited_once()
                self.assertEqual(run.runner.run_experiment.await_args.args[0].num_episodes, 1)

    async def test_invalid_episode_counts_and_contradictory_modes_fail_before_startup(self):
        for module in (run_knockout, run_experiments):
            for arguments in (["--dry-run", "--episodes", "0"],
                              ["--dry-run", "--mock", "--core-engine"],
                              ["--dry-run", "--live"]):
                with self.subTest(module=module.__name__, arguments=arguments):
                    with self.assertRaises(SystemExit) as raised:
                        await self.invoke(module, arguments)
                    self.assertEqual(raised.exception.code, 2)

    async def test_scripted_runs_preserve_the_original_treatment_definitions(self):
        original = run_knockout.KNOCKOUT_CONDITIONS["knockout_full"]
        before = (original.num_episodes, original.use_scripted_creator,
                  original.use_scripted_challenger, list(original.scripted_juror_indices))
        await self.invoke(run_knockout, ["--condition", "knockout_full", "--scripted", "--episodes", "2"])
        self.assertEqual((original.num_episodes, original.use_scripted_creator,
                          original.use_scripted_challenger, original.scripted_juror_indices), before)

    async def test_incentive_comparison_selects_only_exactly_representable_splits(self):
        run = await self.invoke(run_experiments, ["--compare-incentives", "--scripted", "--episodes", "1"])
        self.assertEqual(run.result, 0)
        treatments = [call.args[0] for call in run.runner.run_experiment.await_args_list]
        self.assertEqual(len(treatments), 4)
        self.assertEqual([t.payout.winner_pct for t in treatments], [0.60, 0.80, 0.40, 0.50])


class ProcessExitTests(unittest.TestCase):
    def test_removed_unsupported_treatments_exit_nonzero_without_launching_a_model(self):
        for treatment in ("jury_11", "incentive_equal"):
            with self.subTest(treatment=treatment), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run([
                    sys.executable, str(Path(run_experiments.__file__)), "--treatment", treatment,
                    "--scripted", "--episodes", "1", "--output", directory,
                ], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertIn(f"Unknown treatment: {treatment}", result.stdout + result.stderr)


class DemoTreatmentTests(unittest.TestCase):
    def test_demo_declares_four_adversarial_and_three_honest_jurors(self):
        treatment = run_demo.make_collusion_treatment()
        jurors = [f"juror-{index}" for index in range(7)]
        with tempfile.TemporaryDirectory() as directory:
            runner = ExperimentRunner(Mock(), Path(directory))
            agents = runner._create_agents(treatment, "creator", "challenger", jurors, 0,
                                           oracle_ground_truth=False)
        self.assertEqual(sum(isinstance(agents[juror], AdversarialAgent) for juror in jurors), 4)
        self.assertEqual(sum(isinstance(agents[juror], HonestAgent) for juror in jurors), 3)


if __name__ == "__main__":
    unittest.main()
