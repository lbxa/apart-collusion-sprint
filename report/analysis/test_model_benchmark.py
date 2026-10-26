"""The benchmark pools finished runs per model for one condition, and the table matches the snapshot."""

import json
import unittest

from model_benchmark import COUNTS, ROWS, SNAPSHOT, TABLE, benchmark, render_table, summarise

OPUS, LUNA = "anthropic/claude-opus-5.5", "openai/gpt-6-luna"


def run(run_id, model, state="finished", cell="M1-C1-T1-R1-S1-E1", **counts):
    config = {"cell": cell, "lineup": None, **{f"{role}_model": model for role in ("creator", "challenger", "juror")}}
    summary = {"total_episodes": 2, **{f"block/{name}": counts.get(name, 0) for name in COUNTS},
               "block/truth_verdict_count": 2}
    return summarise(run_id, state, "2026-10-26T04:00:00Z", config, summary)


class ModelBenchmarkTests(unittest.TestCase):
    def test_columns_pool_finished_runs_of_the_shared_condition(self):
        snapshot = {"runs": [
            run("a", OPUS, truth_aligned_verdict_count=2, juror_offer_count=4, juror_accepted_offer_count=1),
            run("b", OPUS, truth_aligned_verdict_count=1, juror_offer_count=2, juror_accepted_offer_count=2),
            run("c", OPUS, state="crashed", juror_offer_count=50),
            run("d", OPUS, cell="M0-C0-T0-R0-S0-E0", juror_offer_count=50),
            run("e", LUNA, truth_aligned_verdict_count=2),
        ]}
        columns = {column["name"]: column for column in benchmark(snapshot)}
        self.assertEqual(sorted(columns), ["GPT-6 Luna", "Opus 5.5"])
        opus = columns["Opus 5.5"]
        self.assertEqual((opus["runs"], opus["episodes"]), (2, 4))
        self.assertEqual((opus["counts"]["juror_offer_count"], opus["counts"]["juror_accepted_offer_count"]), (6, 3))

    def test_rates_keep_counts_and_an_empty_denominator_is_not_zero(self):
        table = render_table({"featured": "GPT-6 Luna", "runs": [
            run("a", OPUS, truth_aligned_verdict_count=1, juror_offer_count=4, juror_accepted_offer_count=1),
            run("b", LUNA, truth_aligned_verdict_count=2),
        ]})
        self.assertLess(table.index("GPT-6 Luna"), table.index("Opus 5.5"), "the featured model comes first")
        self.assertIn("25\\% {\\footnotesize(1/4)}", table)
        self.assertIn("n/a", table, "Luna had no offers, so its acceptance is undefined")
        self.assertIn("\\textbf{100\\% {\\footnotesize(2/2)}}", table, "the unique best verdict rate is bold")

    def test_without_runs_the_table_is_a_template(self):
        table = render_table({"runs": []})
        self.assertIn("Model A", table)
        self.assertEqual(table.count("---"), len(ROWS) * 5 + 5)

    def test_the_committed_table_is_current(self):
        self.assertEqual(TABLE.read_text(), render_table(json.loads(SNAPSHOT.read_text())),
                         "regenerate with model_benchmark.py")


if __name__ == "__main__":
    unittest.main()
