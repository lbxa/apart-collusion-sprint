"""W&B boundary contracts: scientific metadata only, with explicit failures."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from experiments.design import resolve_cell, treatment_for
from experiments.tracking import WandbTracker
from metrics.collector import EpisodeRecord, ExperimentMetrics


class WandbTrackingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.run = Mock(id="run123", url="https://wandb.ai/test/collusion/runs/run123")
        self.run.summary = {}
        self.sdk = Mock()
        self.sdk.init.return_value = self.run
        self.sdk.Table.side_effect = lambda **kwargs: kwargs
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, {"wandb": self.sdk}).start()
        self.treatment = treatment_for(resolve_cell("M0-C0-T0-R0-S0-E0"), num_episodes=1)

    def tracker(self):
        return WandbTracker(
            treatment=self.treatment, name="M0-C0-T0-R0-S0-E0_b1", group="smoke-group",
            project="collusion", entity=None, backend="core", purpose="smoke",
            blocks=1, block_index=1, output_dir=self.output,
            scenario_ids=["clear0"],
        )

    def test_config_and_upload_exclude_credentials_prompts_and_transcripts(self):
        self.treatment.metadata["private_secret"] = "SECRET_METADATA"
        self.treatment.creator_persona = "SECRET_PERSONA"
        record = EpisodeRecord(
            episode_id="ep0", experiment_id="exp0", scenario_id="clear0", treatment="baseline",
            config={"private_context": "SECRET_CONTEXT", "jury_size": 7},
            juror_ids=[f"j{i}" for i in range(7)],
            votes={f"j{i}": "CREATOR_SUPPORTED" for i in range(7)},
            ground_truth=True, outcome="SETTLED_CREATOR", verdict_correct=True, status="completed",
            messages=[{"channel": "public", "content": "SECRET_TRANSCRIPT"}],
            llm_calls=[{"prompt": "SECRET_PROMPT", "response": "SECRET_RESPONSE"}],
            start_time=1, end_time=3,
        )
        metrics = ExperimentMetrics("exp0", "baseline", [record])
        with self.tracker() as tracker:
            tracker.record_results(metrics)
        init = self.sdk.init.call_args.kwargs
        self.assertEqual(init["config"]["cell"], "M0-C0-T0-R0-S0-E0")
        self.assertEqual(init["config"]["factors"], dict.fromkeys("MCTRSEA", 0))
        self.assertEqual(init["config"]["purpose"], "smoke")
        self.assertEqual(init["config"]["backend"], "core")
        self.assertEqual(init["config"]["blocks"], 1)
        self.assertEqual(init["config"]["block_index"], 1)
        self.assertFalse(init["config"]["memory_enabled"])
        settings = self.sdk.Settings.call_args.kwargs
        for key in ("disable_code", "disable_git", "x_disable_meta", "x_disable_stats", "x_disable_machine_info"):
            self.assertTrue(settings[key])
        self.assertEqual(settings["console"], "off")
        uploaded = str(init) + str(self.run.log.call_args_list) + str(self.run.summary)
        self.assertNotIn("SECRET_", uploaded)
        self.assertIn("voting_alignment", uploaded)
        self.assertEqual(self.run.summary["total_episodes"], 1)
        self.run.finish.assert_called_once_with(exit_code=0)
        manifest = [json.loads(line) for line in (self.output / "wandb_runs.jsonl").read_text().splitlines()]
        self.assertEqual(manifest[0]["url"], self.run.url)

    def test_infrastructure_failure_is_a_failed_remote_run(self):
        record = EpisodeRecord("ep0", "exp0", "clear0", "baseline", {"jury_size": 7},
                               status="failed", infrastructure_failure=True,
                               failure_reason="SECRET_FAILURE_PAYLOAD")
        with self.tracker() as tracker:
            tracker.record_results(ExperimentMetrics("exp0", "baseline", [record]))
        self.run.finish.assert_called_once_with(exit_code=1)
        self.assertNotIn("SECRET_FAILURE_PAYLOAD", str(self.run.log.call_args_list))

    def test_model_override_is_captured_for_all_roles(self):
        for role in ("creator", "challenger", "juror"):
            setattr(self.treatment, f"{role}_model", "test/paid-model")
        with self.tracker():
            pass
        config = self.sdk.init.call_args.kwargs["config"]
        for role in ("creator", "challenger", "juror"):
            self.assertEqual(config[f"{role}_model"], "test/paid-model")

    def test_cancellation_and_remote_logging_failure_finish_without_success(self):
        for error in (KeyboardInterrupt(), RuntimeError("remote logging unavailable")):
            with self.subTest(error=type(error).__name__):
                self.run.reset_mock()
                with self.assertRaises(type(error)):
                    with self.tracker():
                        raise error
                self.run.finish.assert_called_once_with(exit_code=1)

    def test_init_failure_does_not_create_a_success_manifest(self):
        self.sdk.init.side_effect = RuntimeError("authentication failed")
        with self.assertRaisesRegex(RuntimeError, "authentication failed"):
            with self.tracker():
                self.fail("Must not start the experiment after W&B initialization fails")
        self.run.finish.assert_not_called()
        self.assertFalse((self.output / "wandb_runs.jsonl").exists())

    def test_remote_log_failure_is_propagated_and_finishes_failed(self):
        record = EpisodeRecord("ep0", "exp0", "clear0", "baseline", {"jury_size": 7},
                               status="completed")
        self.run.log.side_effect = RuntimeError("remote unavailable")
        with self.assertRaisesRegex(RuntimeError, "remote unavailable"):
            with self.tracker() as tracker:
                tracker.record_results(ExperimentMetrics("exp0", "baseline", [record]))
        self.run.finish.assert_called_once_with(exit_code=1)

    def test_manifest_failure_also_finishes_created_run(self):
        with patch.object(Path, "open", side_effect=PermissionError("disk unwritable")):
            with self.assertRaises(PermissionError):
                with self.tracker():
                    self.fail("A run with no local reference must not execute")
        self.run.finish.assert_called_once_with(exit_code=1)


if __name__ == "__main__":
    unittest.main()
