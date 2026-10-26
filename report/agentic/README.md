# Agentic dispute-game case studies

This manuscript describes the 2026-10-26 neutral-prompt Deep Agents campaign.
Its evidence is separate from the older structured-action harness reports.
The [paper brief](../../docs/reporting/paper-brief.md) records A0–A3 and the
claim-to-evidence mapping; [review.md](review.md) records acceptance checks and
submission gaps.

From the repository root:

```sh
make -C report agentic
make -C report agentic-figures PYTHON="$PWD/.harness/report-venv/bin/python"
make -C report agentic
```

The first command builds `report/agentic/build/main.pdf` with the included
vector figure. Figure regeneration uses the report's existing locked
`report/requirements.lock` environment. Open `main.tex` or this directory in
Codex for the source editor and PDF preview. Built outputs remain ignored;
`report.pdf` is the published PDF copy for this campaign.

The committed numeric snapshot is `report/data/agentic-campaign.json`.
Re-admission and raw-export commands are documented in
[harness-v2/README.md](../../harness-v2/README.md). The complete campaign data
were authorized for repository publication:

- `harness-v2/results/campaign-2026-10-26/analysis.json`: validated numeric summary.
- `harness-v2/results/campaign-2026-10-26/export/campaign-index.json`: all 13 runs.
- `harness-v2/results/campaign-2026-10-26/export/experiments/<run-id>.json`:
  original manifest, separate annotations, SHA256 hashes, every JSON/JSONL event
  and recorded text. JSONL files become ordered arrays without truncation.
- `harness-v2/results/campaign-2026-10-26/export/raw-data.zip`: those JSONs plus
  original bytes, including checkpoint databases, input documents and the
  shared spending ledger. Large evidence files use Git LFS; run `git lfs pull`
  after cloning to retrieve their actual contents.

Raw formats differ across the early pilots. Some early model-end records omit
subclass fields; graph traces retain tool-call updates. Only provider-returned
reasoning is observable. An absent field is not proof of absent internal
reasoning or an action that another retained stream records. Original reference
verdict labels cannot score a creator's changed claim; use pinned actual-claim
reviews, and keep ambiguous cases distinct.

## Changelog

### 2026-10-26

- Name Lucas Barbosa and Stefan Gazzana as authors, in that order, as supplied
  by the user; affiliations remain unspecified.
- Keep the clarified-case two-seed comparison separate from original-case
  discovery pilots and memory blocks. Adaptive model selection, semantic
  ambiguity and dependent episodes prevent pooling these into a collusion rate.
- Preserve nulls and the interrupted scheduling pilot with all positive cases.
  The user authorized publishing this full campaign, including original
  trajectories and checkpoints, to the repository through Git LFS.
- Remove the LLM Usage and Execution/accounting appendices as requested.
  This internal draft still records review limitations in its methods and
  supporting evidence; final venue formatting and author details remain open.
