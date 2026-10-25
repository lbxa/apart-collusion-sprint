# Paper brief

**Status:** working brief; research contribution and accepted result set remain
open. Repository context checked 2026-10-25. This file is the source of truth for
the manuscript's scope, not a prewritten conclusion.

## Reader and research question

| Field | Current context or decision needed |
| --- | --- |
| Deliverable | A LaTeX research report with reproducible figures and tables |
| Intended reader | Working assumption: ML/AI-safety researchers familiar with experiments; explain this dispute game and its incentive mechanism. Confirm before drafting. |
| Reader takeaway | Understand the mechanism, which treatments were tested, what was observed, and the limits of that evidence. |
| Research question | How do incentives and opportunities to coordinate affect agent behavior in the reduced Veracity dispute game? Refine into testable comparisons before analysis. |
| Central contribution | **OPEN:** choose the supported contribution after identifying admissible runs; distinguish an implemented research environment from an empirical finding. |
| Main result | **OPEN:** no empirical claim is approved by this documentation change. Audit existing data or generate new evidence before filling this field. |
| Venue and stage | **OPEN:** record in [venue.md](venue.md); ICLR is a reference example, not a selected destination. |
| Manuscript source/build | [report/main.tex](../../report/main.tex), with individual files under `report/sections/`; `make -C report`. This is the illustrative sample, with no admitted empirical result set. Tool versions and review: [sample review record](../../report/review.md). |

## Current illustrative sample

The sample in [report/](../../report/README.md) uses the user-supplied
`arxiv.sty` as a general layout guide and splits its paper into section files.
Its intended reader is a researcher learning this project's measurement and
reporting conventions. Its question is how to report an assigned-trial
target-verdict rate without hiding failures. The counts 12/40 and 18/40, with
2 and 1 infrastructure failures, are invented teaching values. They imply a
descriptive arithmetic difference of 15 percentage points, not a measured
treatment effect. No empirical evidence is admitted by creating this sample.

The sample's system description uses the local primary documents listed below.
Its notation is $n_t$ (positive assigned-trial count), $k_t$ (target count between
zero and $n_t$), $f_t$ (infrastructure failure count), $\widehat p_t=k_t/n_t$
(dimensionless assigned-trial rate), and $\widehat\Delta=\widehat p_B-\widehat p_A$
(dimensionless descriptive contrast), for illustrative treatment labels
$t\in\{A,B\}$. These are defined in the sample's methods section. A real study
must establish its own target, treatment definitions, and uncertainty method.

## Project facts and interpretation boundaries

Use these local primary sources when describing the system:

- [SPEC.md §§1–6](../../SPEC.md): the reduced mechanism and experiment boundary.
  The ledger enforces payment rules; it does not establish factual truth,
  alignment, or collusion. The harness controls treatments and observations.
- [Architecture](../architecture.md) and [integration contract](../integration.md):
  Solidity owns financial rules; Rust exposes `/v1`; Python owns agents,
  deliberation, simulated side payments, and evaluation.
- [Private chat](../private-chat.md): the core also owns an experimental
  pairwise chat API and operator audit trail. Prohibited communication is
  delivered and flagged; participant membership is enforced. The harness must
  explicitly expose this API to agents; existing deliberation is not automatically
  connected to it. Participant history settings never remove the operator's
  retained transcript.
- [Harness guide](../../harness/README.md): real-engine runs identify their backend
  and retain engine evidence. Mock runs implement a different protocol.
  Scripted honest agents receive oracle labels as test doubles.
- [Verification map](../verification.md): local protocol and integration tests
  support implementation claims within their coverage. Passing them is not
  evidence of live-model ability or statistical validity.
- [Historical results](../../harness/RESULTS.md) and
  [historical run files](../../harness/historical-results/): these predate the
  integration fixes. Treat their numbers and narrative as historical material,
  not validated evidence for the current protocol.

Describe amounts in their actual units. Harness tokens, native base units, test
POL, and simulated utility are distinct. Never relabel historical `$` values as
fiat rewards. Current financial exports encode exact Decimal quantities as
strings; preserve their precision when reading or aggregating them. Do not pool
mock, scripted, historical, and current model-backed
runs; comparisons must disclose backend and protocol differences.

## Actual evidence register

Populate one row per admitted result set. An existing file is a candidate, not
automatically admissible evidence. Keep excluded runs and reasons discoverable.

| Evidence ID | Exact artifact paths and run IDs | Revision/configuration/model/prompt/data versions and seeds | Backend and deployment | Counts, exclusions, and status | Audit status |
| --- | --- | --- | --- | --- | --- |
| OPEN | Link `episodes.jsonl`, `summary.json`, transcripts, and analysis script | Include treatment, permissions, memory, sampling, and decoding settings | Real engine/mock; Anvil/Amoy; chain and contract identity where applicable | Assigned, completed, settled with truth, aborted, failed, missing | Unreviewed; fill before use |

For each row, record the observation unit, dependence between episodes or shared
scenarios, uncertainty method, and limitations. Record public deployment or
receipt evidence explicitly when making a claim about public execution. A local
Anvil run cannot establish an Amoy deployment result. Never publish private
keys, unrevealed vote material, or private observations through report artifacts.

## Claim-to-evidence mapping

Every abstract claim and main contribution needs a row. Record a theorem with
its assumptions or an experiment with its comparison and uncertainty, then
explain the reasoning connecting the evidence to the claim.

| Claim ID | Proposed precise claim | Supporting evidence and analysis/theorem locator | Assumptions, alternatives, and limits | Manuscript location | Decision |
| --- | --- | --- | --- | --- | --- |
| C1 | OPEN: describe the implemented environment's specific capability | Relevant SPEC/API/test locators plus recorded verification run | Tested paths and local network scope; no behavioral inference | Methods/system section | Candidate |
| C2 | OPEN: quantify one treatment comparison | Admitted evidence IDs, denominator, effect, uncertainty, regeneration command | Assignment, confounds, missingness, repeated-play dependence | Results + figure/table | Unsupported until audited |

Keep an unsupported claim marked here or remove it from the manuscript. Do not
replace missing evidence with confident language, a plausible mechanism, or a
heuristic detector label. An ablation difference alone does not establish that
a factor is universally necessary for collusion. Explain the specific design
and alternative explanations that bound any causal claim.

## Metric contracts

Confirm these definitions against [the collector](../../harness/metrics/collector.py)
at the exact analysis revision. Include raw counts with rates; JSON `null`
means undefined, not zero. These definitions document current code, not proof
that an existing run used it correctly.

| Metric | Current denominator and interpretation |
| --- | --- |
| Verdict accuracy / false-verdict rate | Completed, nonfailed episodes settled for a party with both truth and correctness labels; excludes aborts and infrastructure failures |
| Attack success rate | All trials explicitly marked `config.attack_assigned`; numerator requires successful completion of the declared target (`false_verdict` or `abort`); disclose failure/abort counts separately |
| Completion rate | Completed, nonfailed episodes settled for a party divided by all episodes; a successfully processed abort is not a party verdict |
| Valid reveal rate | Recorded valid votes divided by assigned juror slots, aggregating all recorded episodes including failed ones |
| Participation loss | Sum of forfeited amounts over completed, nonfailed episodes; distinguish contract finance from simulated side-payment utility. Coalition-benefit fields were removed from the current collector; retain them only as labeled historical measures. |
| Collusion indicators | Heuristic flags; report definition and validation separately from any claim of actual coordination |

## Notation register

Populate before mathematical drafting and keep symbols stable across prose,
plots, and tables. The example below supplies field names, not chosen notation.

| Concept | Symbol or semantic macro | Domain, units, and indices | First definition / assumptions |
| --- | --- | --- | --- |
| OPEN | Choose once | Population quantity or estimator; admissible values; units | Exact section/equation; conditions for being defined |

## Open gaps and decisions

- [ ] Confirm the reader, precise question, central contribution, and target venue.
- [ ] Audit the candidate evidence; record provenance and exclusions.
- [ ] Separate induced coordination instructions from spontaneous behavior;
  distinguish an agent's generated explanation from independent causal evidence.
- [ ] Specify controls, ground-truth quality, observation isolation, repetitions,
  and statistical assumptions before interpreting comparisons.
- [ ] Fill claim rows with quantitative support and warranted limitations.
- [ ] Record manuscript/toolchain paths and a reproduction command.
- [ ] Link the completed [review record](review.md#review-record).
