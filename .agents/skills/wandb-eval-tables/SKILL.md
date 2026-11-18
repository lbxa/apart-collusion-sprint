---
name: wandb-eval-tables
description: "Convert W&B Table artifacts into non-destructive EvalTable previews with scan-first planning, typed input/output/score columns, bounded batches, verification, and safe removal. Use when a coding agent needs to create, inspect, compare, verify, or remove W&B EvalTable previews."
---
<!--
SPDX-FileCopyrightText: 2026 CoreWeave, Inc.
SPDX-License-Identifier: Apache-2.0
SPDX-PackageName: skills
-->

# W&B EvalTable previews

Use the bundled helper to preview existing `wandb.Table` data as
`wandb.EvalTable` data. A preview creates new runs and keys; it never overwrites
the source runs or tables.

Read `references/EVAL_TABLES.md` before converting. It is the canonical source
for EvalTable semantics, source selection, limits, column roles, verification,
and removal.

## Environment

From the repository root, use the harness's locked W&B SDK and supply Weave
as a temporary `uv` dependency. Confirm that the selected SDK exposes
`wandb.EvalTable` before conversion:

```bash
uv run --project harness --locked --with weave \
  python .agents/skills/wandb-eval-tables/scripts/table_artifact_to_eval_table.py --help
```

For sprint work pass `lbxa-corp/apart-collusion-sprint` explicitly. Follow
[AGENTS.md](../../../AGENTS.md) for the standard W&B host and credential loading.
When the key is in the ignored root `.env`, load it using `python-dotenv` with
existing environment values preserved. Scan only in an authorized source
project. Preview numeric or provenance projections by default. A preview
duplicates table contents into W&B and Weave, so private transcripts, raw
calls, and evaluator-only material require explicit release authorization.

## Required workflow

1. Choose the narrowest source that matches the request: exact artifact, one
   run, one sweep, or a project/workspace. Do not broaden an explicitly named
   source.
2. Run `scan`. This is read-only preflight and is not proof of conversion.
3. Review `eligible_summary_by_table_key`, table shapes, truncations, warnings,
   and existing-preview metadata. Select one table key unless the user asks for
   a broader batch.
4. Classify columns only when confident. Input tuples must uniquely identify
   rows; score columns must be numeric or boolean; free-text labels and
   rationales are outputs. Leave ambiguous tables untyped.
5. Run `preview` for exactly one `--table-key` per invocation. Keep the target
   in the source project unless the user requests another writable project.
6. If runs were created, run `verify-preview` on the final created run and the
   exact logged key. Report success only when it returns `verified: true`.
7. Report created and skipped sources plus every truncation or failed check.

```bash
T=.agents/skills/wandb-eval-tables/scripts/table_artifact_to_eval_table.py

uv run --project harness --locked --with weave python "$T" scan \
  --source-workspace lbxa-corp/apart-collusion-sprint --max-runs 4

uv run --project harness --locked --with weave python "$T" preview \
  --source-workspace lbxa-corp/apart-collusion-sprint \
  --target-project lbxa-corp/apart-collusion-sprint \
  --max-runs 4 \
  --table-key predictions

uv run --project harness --locked --with weave python "$T" verify-preview \
  --run lbxa-corp/apart-collusion-sprint/PREVIEW_RUN_ID \
  --table-key predictions_preview
```

## Safety

- `scan` and `preview --dry-run` are read-only. `preview` creates W&B runs,
  EvalTables, and Weave evaluations; run it only when the user requested a
  conversion.
- The helper caps tables at 10,000 rows and 100 columns, warns above 1,000
  rows, and refuses more than 50 eligible table artifacts for one key. Surface
  every cap; never imply a truncated preview is complete.
- Do not bypass helper failures with ad-hoc logging. Narrow or correct helper
  arguments, then retry only when the change is safe.
- Removal deletes both Weave evaluations and preview runs. Run
  `delete-preview --dry-run` first, verify every target is helper-created, and
  obtain confirmation before the irreversible invocation. Never delete source
  runs.
