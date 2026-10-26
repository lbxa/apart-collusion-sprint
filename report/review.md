# Baseline report review

Reviewed **2026-10-25** against the [reporting checklist](../docs/reporting/review.md).
Decision: **reviewed internal smoke report**, not a submission-ready treatment study.

## Evidence and scope

- **Admitted evidence:** B0 in the [paper brief](../docs/reporting/paper-brief.md),
  W&B run `m073at4i`, cell `M0-C0-T0-R0-S0-E0`, two live-model episodes in one
  block, seven jurors and three public rounds, core backend on local Anvil.
- **Observed counts:** 2/2 correct settled verdicts, 14/14 valid and truth-aligned
  reveals, 42/42 agreeing within-episode juror pairs, 42 public messages and zero
  private messages. Same-side repetition is 0/7 and repeated correctness is 7/7
  across one episode pair. No collusion or treatment-effect inference is admitted.
- **Exclusions:** free-route run `2vu0jc3u` failed both assigned episodes after
  quota exhaustion. It remains an operational failure record and is not pooled
  into the successful retry's behavioral means. Scripted, historical, mock, and
  the former fictional teaching results are excluded.
- **Failed-attempt audit:** separately reconciled the free run's two failed,
  zero-completed records and HTTP 429 daily-quota reasons. Summary source:
  `.harness/experiments/jury-baseline-smoke-2026-10-25/all_results.json`, SHA256
  `e4506bf95f27f19849892f44c165c1341368d09e434a5f5f97f79817e7ab3124`.
  Episode source under that directory:
  `exp_exp_m0c0t0r0s0e0_f62b0414/episodes.jsonl`, SHA256
  `e5a917a45202172e32d4174afa9123d71fd63e95ae2c2e1d120f9d12fb1ed325`.
  This exclusion is manually audited here, not recalculated by the plot renderer.
- **Observation unit:** means and sample SD use episode values, with denominator
  `n - 1` for SD. The rate and runtime samples have `n = 2`; votes and pairs are
  measurement denominators, not independent experimental replicates. The single
  cross-episode pair has no estimable sample SD. Disabled-channel abuse rates
  remain unavailable, not measured zeros.
- **Numerical reconciliation:** each reported rate is 100% in both episodes,
  yielding observed SD zero. Episode durations are 76.3070654579 and
  79.0901371250 seconds, with mean 77.6986012915 and sample SD 1.9679288483
  seconds. This descriptive spread is neither a confidence interval nor a
  controlled latency benchmark.
- **Provenance:** the execution recorded `e0a5c68` with a dirty working tree;
  integration changes were subsequently committed as `47636e9`. The committed
  safe snapshot records source SHA256 hashes, recorded configuration, local
  deployment identity, and a separately labeled prompt hash at analysis time.
  The snapshot excludes content, credentials and unrevealed votes.

## Reproduction and toolchain

| Check | Recorded result |
| --- | --- |
| Manuscript | `main.tex`, `preamble.tex`, and `sections/*.tex` |
| PDF | `build/main.pdf`, five US Letter pages; editor build also writes `main.pdf` |
| Stage | Internal report; no submission venue, page limit, anonymity claim or final author list |
| Template | Supplied `arxiv.sty` unchanged; attribution in `template/README.md` |
| Python | 3.12.11 in `.harness/report-venv`; separate from the harness runtime |
| Figure packages | Matplotlib 3.11.2, NumPy 2.5.4, PyYAML 6.0.3; transitive versions pinned in `requirements.lock` |
| Figure regeneration | `make -C report figures PYTHON="$PWD/.harness/report-venv/bin/python"`; exit 0; `.harness/report-figures.log` |
| Source audit | Regenerated `build/baseline-snapshot-audit.json` with `--source --config --snapshot-only`; byte-identical to `data/baseline-smoke.json` |
| Analysis tests | Ten tests for sample SD, missing/one-observation SD, zero spread, admission, channel controls, revealed-vote counts and settled-verdict correctness; all passed |
| TeX | pdfTeX 3.141592653-2.6-1.40.27, TeX Live 2025; Latexmk 4.86a |
| Bibliography | Keyed `thebibliography`; no external backend |
| Clean build | `make -C report clean`, then `make -C report`; exit 0; `.harness/report-build.log` |
| Editor build | `latexmk -pdf -synctex=1 -interaction=nonstopmode -halt-on-error -file-line-error main.tex` from `report/`; `.harness/report-editor-build.log` |
| Compilation diagnostics | No errors, undefined references/citations, missing glyphs, overfull or underfull boxes in the final clean-build log |
| Repository gate | `bash scripts/verify.sh`; exit 0 with local Anvil permitted. Hooks, 32 Solidity tests, Rust checks/tests/builds, 216 Python tests and harness acceptance suite passed; `.harness/verification-report-figures-2026-10-25.log` |

The normal figure command reads only the committed safe snapshot. A report-only
checkout can therefore regenerate charts without the ignored original transcripts
or any model credentials. Ordinary TeX builds use the included vector PDFs and
do not need Python. Execution nondeterminism and the dirty original source state
prevent claiming exact replay of the model experiment from a pristine revision.

## Figure and rendered-page acceptance

- **Physical sizes:** outcomes 6.5 by 3.05 inches; process 6.5 by 2.75 inches.
  Figures are included at text width, with minimum 8.5-point labels, serif STIX
  typography, explicit marker shapes and direct role labels.
- **Uncertainty:** blue means use pale solid blue SD regions, opacity 1. Zero-SD
  regions collapse without an artificial minimum width. Runtime shows a genuine
  mean-plus/minus-SD interval. Captions identify sample size, units, exclusions,
  dependence and the difference between descriptive spread and uncertainty.
- **Outputs:** vector PDFs plus 300-dpi PNGs. Pypdf checks confirmed embedded
  font streams for every chart font and all 17 fonts in the compiled manuscript.
- **Accessibility:** both figures were inspected in grayscale and simulated
  severe deuteranomaly. Circle/square episode marks, mean diamonds, and `Cr`/`Ch`
  matrix labels preserve distinctions without relying on color alone. QA images
  are retained under `/tmp/baseline-*-grayscale.png` and
  `/tmp/baseline-*-deuteranomaly.png`.
- **Page review:** inspected all five pages rendered at 110 dpi, including both
  figures at final width, the architecture diagram, equations, result table,
  captions and references. An initial outcome xlabel/footer overlap was fixed;
  a long-path bibliography spacing warning was resolved. Final renders are in
  `build/pages/`; no clipped marks, overlapping labels or broken references found.

## Open gaps

The 20-episode first pass, independent additional blocks, matched evidence
variants, factor contrasts, power and multiplicity planning, auditor-agent
implementation, final author list and submission venue remain open. Two selected
clear scenarios cannot establish population accuracy, a treatment effect or an
absence of collusion. This review supersedes the earlier fictional-sample review;
that sample's counts remain available only as reporting-guide examples.

## Revision review: exploratory probes

```text
Review date / reviewer: 2026-10-25 / Claude Code session, for the project team
Source revision / dirty changes: e5b3eb3 plus this revision's report, brief and analysis changes
Manuscript path / PDF path: report/main.tex; checked build at a scratch path (not committed)
Venue, year, track, stage / rules checked at: internal report; no venue selected (venue.md unchanged)
Evidence IDs and analysis revision: B0 unchanged; probes X1–X6 (paper brief), snapshot data/exploratory-probes.json
Figure/table regeneration commands and output paths: `make -C report tables` (reads the committed
  snapshot, writes tables/exploratory-probes.tex); snapshot refreshed from the ignored originals with
  `harness/.venv/bin/python report/analysis/probe_snapshot.py --extract --experiments .harness/experiments`.
  Baseline figures unchanged.
Compiler / distribution / package and bibliography versions: Tectonic 0.17.0 (Homebrew), on-demand
  bundle packages; keyed thebibliography. The recorded pdfTeX/TeX Live 2025/Latexmk 4.86a toolchain is
  not installed on this machine, so the official `make -C report` build was not run.
Clean build command / exit status / log: `tectonic --keep-logs --outdir <scratch> main.tex` from report/;
  exit 0; 7 US Letter pages; no errors, undefined references or citations, missing glyphs or overfull
  boxes; one underfull \vbox at the first page break (extra space after the introduction), accepted.
Pages and figures inspected at final size: all 7 pages rendered at 110 dpi; Table 2 fits the text width
  with its caption above; baseline figures, equations and Table 1 unchanged; references resolve.
Scientific and reader-comprehension findings: each probe is one episode, reported as counts with no
  rate, mean or SD; compared pairs and their revisions are named; X2's auditor observations are
  excluded because its case file marked both of a juror's offers accepted; the monitor is presented
  as uncalibrated heuristic labels. Earlier session claims that jurors widely denied payments to the
  auditor came from X2's contaminated interview and are not reported. Analysis tests: 3 probe tests
  and the existing baseline tests pass.
Accepted warnings / not-applicable checks and reasons: the underfull page-break box above; no new
  figure, so grayscale and colour-vision checks are not applicable to this revision.
Open gaps / responsible person / next action: official pdfLaTeX build of this revision (project team);
  repeated probe blocks, true-claim scenarios, other models, monitor calibration and validation.
Decision: draft
```

## Revision review: model benchmark template

```text
Review date / reviewer: 2026-10-26 / Claude Code session, for the project team
Source revision / dirty changes: 7e5fb60 plus this revision's benchmark section, script, data and docs
Evidence IDs and analysis revision: none admitted; data/model-benchmark.json holds no runs
Figure/table regeneration commands and output paths: `make -C report tables` renders
  tables/model-benchmark.tex from the committed snapshot; W&B runs enter only through
  `model_benchmark.py --fetch --since <UTC time>`.
Compiler / clean build: Tectonic 0.17.0 as in the previous revision; exit 0; 7 US Letter pages; no
  errors, undefined references or overfull boxes; the earlier underfull page-break box remains.
Pages inspected at final size: page 6 at 110 dpi; Table 3 fits the text width, its shaded featured
  column runs unbroken between the booktabs rules, and every value reads as pending.
Scientific and reader-comprehension findings: the table shows no numbers until runs are admitted;
  its caption defines pooling, rates with counts, n/a for zero denominators, shading and bold.
  Analysis tests: 4 benchmark tests and 3 probe tests pass.
Accepted warnings / not-applicable checks and reasons: no figure, so grayscale and colour-vision
  checks do not apply; shading and bold repeat information the values and caption already carry.
Open gaps / responsible person / next action: fetch and admit the model-screen runs (project team);
  official pdfLaTeX build.
Decision: draft (template)
```
