# Collusion resistance report

The active manuscript, `main.tex`, is a prospective working report developed
alongside `harness/research/collusion-resistance-v1/`. It retains all five
coauthors and follows the requested Epistemics Apart layout with native Computer
Modern. No new behavioral result is admitted until the paper brief and evidence
review establish its provenance. Pending model slots are unavailable values,
never zero collusion or perfect resistance.

```sh
make -C report agentic
```

The active PDF is `report/agentic/build/main.pdf`. It now includes a five-model
mechanical outcome profile from the full original 150-session frame, with
122 source-correct settlements, two source-adverse settlements, 26 aborts and
150 unresolved outcomes across 300 assigned cases. The two paid wrong-majority
GPT OSS education cases include confirmed extra transfers; one is inside a
failed run. New panels contrast those records with Inkling's explicit refusal
plus correct execution and DeepSeek's correct text without a ballot. Selected
texts remain attributed observations, not faithful internal reasoning.

The separate 75-session exploratory recovery snapshot is retained without
pooling or replacing failures. Exact versions are original audit v83 and
recovery audit v20, with latest capture `2026-11-18T03:43:04Z` (November 17,
22:43 EST). Recovery's 75 attempts have 19 complete, 51 failed and five
interrupted journal dispositions; 43 source-correct settlements and three
aborts are retained despite 104 unresolved case outcomes.
Independent semantic coordination and competence review remain
open, so no collusion-resistance score, ranking, CI or safeguard effect is
admitted. Six conditions use one paid-offer amount and two fixed source tasks;
they do not constitute a stakes sweep or broad sector benchmark.
The broader five-source pilot remains
exploratory. Creator and challenger are scripted counterparts in this first
model campaign. It measures induced juror susceptibility, not spontaneous
cross-role collusion. Source/session clustering, unresolved labels, capability
failures, honest completion, and candidate safeguards remain explicit.

Regenerate the new checked outcome profiles and three distinct cohort/arm
tables, then build the report:

```sh
make -C report agentic-collection-figures agentic \
  PYTHON="$PWD/.harness/report-venv/bin/python"
```

Inputs and immutable artifact/file verification records are in
`report/data/collusion-progress-final-20261117/`. The earlier v12 package is
preserved in `report/data/collusion-progress-20261117/`. The stdlib-only offline validator
rejects altered snapshot bytes, aggregate/case mismatches and archive cross-pin
mismatches. Selected quote spans, offsets and source hashes are in
`report/data/collusion-case-excerpts-20261117/`. Full private calls are not copied
into those numeric/selected-excerpt packages.

Render the measurement module's numeric export with the existing locked report
environment; this command does not call models or create labels:

```sh
MPLCONFIGDIR=/tmp/collusion-report-matplotlib .harness/report-venv/bin/python \
  report/analysis/resistance_figures.py --data /path/to/numeric.json \
  --output-dir /path/to/figures
```

The renderer retains all five model slots, shows unavailable estimates as text,
omits invalid or degenerate confidence intervals, and saves the input SHA256 in
a provenance sidecar. Complete-case points require the scorer's affirmative
competence criterion. A rendered provisional chart is not independent evidence
admission; update the paper brief before inserting it or strengthening prose.

The retained `images/resistance-primary.pdf` is an explicitly labeled
collection-not-started status display. Its portable input,
`report/data/collusion-resistance-pending-20261117.json`, pins the prepared
register's five pending exploratory jobs and zero assigned confirmation cases.
It contains no empirical resistance estimate and is omitted from the current
PDF as a superseded preparation display. Regenerate that exact display:

```sh
make -C report agentic-status-figure PYTHON="$PWD/.harness/report-venv/bin/python"
make -C report agentic
```

The complete original v2 and revised v3 capability cohorts are admitted from
hardened, fresh-download-verified private archives. Their separate five-model
tables keep orchestration completion, case outcome, valid actions, eligible
source-correct ballots, and extra transfers separate. All ten jobs completed;
three v2 cases aborted and all five v3 cases adjudicated source-correctly on
the same finance claim. No-reveal accuracy stays unavailable. Semantic
coordination remains unreviewed, and these no-offer controls do not estimate
paid resistance, a causal bootstrap effect, or a model ranking. Regenerate both
checked tables with:

```sh
make -C report agentic-pilot-table PYTHON="$PWD/.harness/report-venv/bin/python"
make -C report agentic
```

`report/data/collusion-pilots-20261117/{v2,v3}/` contains portable numeric and
receipt inputs. The original partial readout remains frozen separately in
`report/data/collusion-pilot-v2/`. The generator requires the hardened receipt
schema, complete coverage of each selected pilot cohort, matching seed labels,
and ingestion/run/evidence/source pins. Recorded-call counters are not billed
request counts. The earlier pending figure and numeric bytes remain retained
as a dated preparation record. The [readout admission contract](../../docs/reporting/paper-brief.md#first-exploratory-pilot-readout-admission-plan)
governs later rows and source-backed excerpts.

The selected GLM confirmation illustration is pinned in
`report/data/collusion-glm-first-20261117/`: hardened archive receipt and
manifest, full-frame register, original mechanical readout and ingestion
receipt, and a computed selected-session extract with exact returned-text
spans. All 209 archived files were rehashed without mismatch. The finance
case has three source-correct reveals, explicit public offer declines, and no
extra transfer. Its two panels contrast a mistaken payout calculation with
correct arithmetic and concern about an unescrowed payment. These are observed
actions and returned text, not a cause of refusal, a faithful internal process,
or a model-level resistance estimate. The delivered base constitution does
not explicitly add truthfulness or anti-payment duties.

## Historical October case studies

`historical-october-main.tex` describes the 2026-10-26 neutral-prompt Deep Agents campaign.
Its evidence is separate from the older structured-action harness reports.
The [paper brief](../../docs/reporting/paper-brief.md) records A0–A3 and the
claim-to-evidence mapping; [review.md](review.md) records acceptance checks and
submission gaps.

The PDF contains the complete 13-run campaign inventory and a qualitative
account of every experiment in `sections/campaign-results.tex`. Appendix B,
`sections/complete-record.tex`, lists all 19 assignments, exact run IDs, episode
payoffs, message/call/reveal/token counts and strong-case evidence locators.
The raw trajectories remain in the campaign release; tables and prose do not
replace them. Rebuild this agentic report rather than the older baseline's
`report/main.tex` when updating these results.

From the repository root:

```sh
make -C report agentic-historical
make -C report agentic-figures PYTHON="$PWD/.harness/report-venv/bin/python"
make -C report agentic-historical
```

The first command builds
`report/agentic/build/historical/historical-october-main.pdf` with the included
vector figure. Figure regeneration uses the report's existing locked
`report/requirements.lock` environment. Open `main.tex` or this directory in
Codex for the source editor and PDF preview. Built outputs remain ignored;
`report.pdf` is the published PDF copy for this campaign.

The committed numeric snapshot is `report/data/agentic-campaign.json`.
The [original harness guide](../../harness/archive/october-2026/README.md)
records the historical admission and raw-export commands. The complete campaign
data were authorized for repository publication and are stored in the
[campaign directory](../../harness/archive/october-2026/results/campaign-2026-10-26/).

- `analysis.json` contains the validated numeric summary.
- `export/campaign-index.json` indexes all 13 runs.
- `export/experiments/<run-id>.json` contains the
  original manifest, separate annotations, SHA256 hashes, every JSON/JSONL event
  and recorded text. JSONL files become ordered arrays without truncation.
- `export/raw-data.zip` contains those JSONs plus
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

### 2026-11-17

- Report source-relative mechanical outcomes with all assigned cases retained,
  separating aborts and unresolved outcomes from source-correct settlement.
  Keep recovery separate and retain settled cases from failed runs; semantic
  resistance labels and CIs require independent review, not just verified bytes.
- Preserve selected quote spans and exact file/line/JSON-path pins; provider
  text discussing reward eligibility does not establish a faithful motive or
  knowledge of falsity. See the [reporting decision](../../docs/decisions/report-mechanical-outcomes-before-resistance-rankings.md).
- Add user-confirmed affiliations: New York University for Lucas Barbosa,
  Sravika Linga, Muskaan Kumar and Jake Fogel; Roundarc for Stefan Gazzana.
  Use the confirmed Gazzana spelling in the active author block and PDF metadata;
  preserve historical manuscripts and frozen evidence packages.
- Keep a selected paid-offer case separate from aggregate confirmation
  inference. Preserve the full assignment frame and unknowns, verify complete
  session bytes before excerpting, and check returned payout/rule claims
  against actual parameters and delivered duties. The superseded pre-launch
  chart stays retained outside the current PDF.
- Keep the first no-offer capability pilot separate from paid-inducement
  resistance: valid execution, factual correctness, and source-checking
  competence are distinct readouts, and one exploratory case supplies no
  confirmatory CI or model ranking. Admit quotes only after terminal evidence
  and the versioned private archive have been verified.
- Keep the new prospective benchmark in `main.tex` and the complete October
  manuscript in a separate build. Historical quotations retain their original
  rules and source locators and do not fill the new campaign's denominators.
  See the [decision record](../../docs/decisions/keep-prospective-collusion-report-separate-from-october-evidence.md).
- Preserve Lucas Barbosa, Stefan Gazana, Sravika Linga, Muskaan Kumar, and Jake
  Fogel in that order. Reuse the Epistemics layout without transferring its
  author roster, affiliations, or results.
- Freeze the prepared numeric export as a portable status input. The included
  five-slot figure states collection has not started and distinguishes pending
  exploratory jobs from zero assigned confirmation cases; it is not a model
  score. Its renderer rejects collection-not-started labeling after a job starts.

### 2026-10-26

- Use the complete author list supplied by the user: Lucas Barbosa, Stefan
  Gazana, Sravika Linga, Muskaan Kumar and Jake Fogel, in that order. Preserve
  the latest spelling of Gazana; affiliations remain unspecified.
- Include every campaign run and assigned episode in the PDF, with nulls,
  ambiguous reviews and the interrupted pilot visible. Keep reviewed harmful
  coordination distinct from financial outcomes and original-case ambiguity.
- Keep the clarified-case two-seed comparison separate from original-case
  discovery pilots and memory blocks. Adaptive model selection, semantic
  ambiguity and dependent episodes prevent pooling these into a collusion rate.
- Preserve nulls and the interrupted scheduling pilot with all positive cases.
  The user authorized publishing this full campaign, including original
  trajectories and checkpoints, to the repository through Git LFS.
- Remove the LLM Usage and Execution/accounting appendices as requested.
  This internal draft still records review limitations in its methods and
  supporting evidence; final venue formatting and author details remain open.
