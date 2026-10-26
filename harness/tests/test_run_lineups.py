"""The lineup launcher starts one run per (cell, lineup) without starting models or engines."""

import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_lineups
from experiments.design import LINEUPS


def option(command, name):
    return command[command.index(name) + 1]


class LineupLauncherTests(unittest.TestCase):
    def launch(self, arguments, returncodes=None):
        commands = []

        def fake_run(command, stdout, stderr):
            commands.append(command)
            return SimpleNamespace(returncode=(returncodes or {}).get(option(command, "--lineup"), 0))

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(run_lineups.subprocess, "run", side_effect=fake_run), \
             contextlib.redirect_stdout(io.StringIO()):
            result = run_lineups.main(["--output", directory, *arguments])
            logs = sorted(path.name for path in Path(directory).glob("*.log"))
        return result, commands, logs

    def test_each_cell_runs_once_per_lineup_in_one_group_with_passed_options(self):
        first, second = list(LINEUPS)[:2]
        result, commands, logs = self.launch(["M0-C0-T0-R0-S0-E0", "V", "--lineup", first, second, "--jobs", "1",
                                              "--", "--wandb", "--episodes", "1"])
        self.assertEqual(result, 0)
        expected = [(cell, lineup) for cell in ("M0-C0-T0-R0-S0-E0", "M1-C1-T1-R1-S1-E1-V1")
                    for lineup in (first, second)]
        self.assertEqual([(option(c, "--cell"), option(c, "--lineup")) for c in commands], expected,
                         "lineups of one cell are adjacent, so they run side by side")
        self.assertEqual(len({option(c, "--wandb-group") for c in commands}), 1)
        self.assertEqual(len({option(c, "--output") for c in commands}), 4)
        self.assertTrue(all(c[-3:] == ["--wandb", "--episodes", "1"] for c in commands))
        self.assertEqual(logs, sorted(f"{cell}_{lineup}.log" for cell, lineup in expected))

    def test_every_lineup_runs_by_default(self):
        _, commands, _ = self.launch(["M0-C0-T0-R0-S0-E0"])
        self.assertEqual(sorted(option(c, "--lineup") for c in commands), sorted(LINEUPS))

    def test_a_failed_run_fails_the_batch_without_stopping_the_others(self):
        first, second = list(LINEUPS)[:2]
        result, commands, _ = self.launch(["M0-C0-T0-R0-S0-E0", "--lineup", first, second], {first: 1})
        self.assertEqual(result, 1)
        self.assertEqual(len(commands), 2)

    def test_an_invalid_cell_is_rejected_before_any_run_starts(self):
        with patch.object(run_lineups.subprocess, "run") as run, \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run_lineups.main(["M9-C0-T0-R0-S0-E0"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
