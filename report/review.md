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
