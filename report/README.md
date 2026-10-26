# Veracity baseline integration report

This internal report presents the first all-off jury smoke run, using the
supplied `arxiv.sty` and the existing sectioned manuscript. It replaces the
previous fictional teaching comparison with two live Nemotron episodes on the
Rust/Anvil backend. Both verdicts and all 14 revealed votes matched evaluator
truth. These observations establish integration readiness only; they do not
establish an absence of collusion or a treatment effect.

## Files

| File | Purpose |
| --- | --- |
| [main.tex](main.tex) | Main document; orders the section inputs |
| [preamble.tex](preamble.tex) | Packages, semantic macros, diagram styles, and template overrides |
| [arxiv.sty](arxiv.sty) | Supplied single-column style, preserved byte-for-byte |
| [Abstract](sections/abstract.tex) | Integration question, observations, and scope |
| [Introduction](sections/introduction.tex) | Motivation and report aims |
| [Research environment](sections/system.tex) | Mechanism and system-boundary diagram |
| [Methods](sections/methods.tex) | Endpoint, notation, denominator, and uncertainty assumptions |
| [Results](sections/results.tex) | Actual smoke measurements, counts, and two data figures |
| [Exploratory probes](sections/probes.tex) | Six single-episode DeepSeek probes: design, results table and observations |
| [Discussion](sections/discussion.tex) | Interpretation and limitations |
| [Conclusion](sections/conclusion.tex) | Supported takeaway |
| [References](sections/references.tex) | Keyed references to inspected local primary documents |
| [Outcome figure](figures/baseline-outcomes.pdf) | Episode-level rates and the revealed-vote matrix |
| [Process figure](figures/baseline-process.pdf) | Deliberation rates and episode duration spread |
| [Analysis script](analysis/baseline_figures.py) | Safe source extraction, validated calculations, and Matplotlib rendering |
| [Admitted data](data/baseline-smoke.json) | Public revealed votes, counts, timing, and source provenance; no message bodies |
| [Probe data](data/exploratory-probes.json) | Content-free counts, settings and source hashes for probes X1–X6 |
| [Probe script](analysis/probe_snapshot.py) | Extracts the probe snapshot from local exports and renders its table |
| [Probe table](tables/exploratory-probes.tex) | Generated results table for the probes; do not edit |
| [Model benchmark](sections/benchmark.tex) | Per-model benchmark table; a template until model-screen runs are admitted |
| [Benchmark data](data/model-benchmark.json) | Content-free W&B run settings and counts for the benchmark |
| [Benchmark script](analysis/model_benchmark.py) | Fetches run summaries from W&B and renders the benchmark table |
| [Benchmark table](tables/model-benchmark.tex) | Generated benchmark table; do not edit |
| [Makefile](Makefile) | Compiles the document; regenerates the figure on request |
| [Template provenance](template/README.md) | Attachment attribution, hashes, and adaptation decisions |
| [Review record](review.md) | Evidence, build, and final-size rendered checks |

Only `main.tex` is a standalone document. Edit prose in `sections/`, keep common
formatting in `preamble.tex`, and change section order through `main.tex`.
The current figure generator lives in `analysis/`; general style guidance and
the former fictional example remain in [the reporting guide](../docs/reporting/README.md).

## Build

### TeXShop on macOS

Open `report/main.tex` in TeXShop and press **Typeset** (Cmd-T). The first-line
directive selects `pdflatexmk`, which runs pdfLaTeX until citations and
cross-references stabilize. Each section and `preamble.tex` has a root-file
directive, so Cmd-T from those files also builds the whole report. The figure
PDF is included in `figures/`; no Python setup or figure-generation step is
needed to typeset the report.

TeXShop writes **`report/main.pdf`**, `main.aux`, `main.log`, and SyncTeX data
beside `main.tex`. These build products are ignored by Git. The `pdflatexmk`
engine ships with TeXShop; if it is not in the engine menu, move
`pdflatexmk.engine` from `~/Library/TeXShop/Engines/Inactive/Latexmk/` into
`~/Library/TeXShop/Engines/` and restart TeXShop. Alternatively, select LaTeX
and typeset repeatedly until there are no rerun warnings. The tiny keyed
`thebibliography` needs no BibTeX or Biber pass.

If the console is waiting for another filename after a failed build, press
**Abort**, then typeset again. LaTeX creates `main.aux`; do not create it by hand
or trash auxiliary files while typesetting. Use **Trash Aux Files** only after
stopping a build, then rerun `pdflatexmk` to regenerate them.

### Command line

From the repository root:

```sh
make -C report
```

Requirements: Make, `latexmk`, pdfLaTeX, and the standard
Geometry, Fancyhdr, T1 Times fonts, AMS, Booktabs, graphics, Microtype, TikZ, and
Hyperref packages. `LATEXMK` can select an installed executable.

The PDF is **`report/build/main.pdf`**. The output directory also holds the TeX
log and temporary files; it is ignored by Git. `make -C report clean` removes
LaTeX build products and report PDFs from both editor and command-line builds,
preserving the included figures. Run cleanup only when no build is active.

### Regenerating the probe table

`make -C report tables` renders `tables/exploratory-probes.tex` from the committed
snapshot with the standard library only. To re-admit the probes from the ignored
original exports, run
`harness/.venv/bin/python report/analysis/probe_snapshot.py --extract --experiments .harness/experiments`
from the repository root. Its tests run with `python3 -m unittest test_probe_snapshot`
from `report/analysis/`.

### Regenerating the model benchmark

`make -C report tables` also renders `tables/model-benchmark.tex` from the committed
snapshot. To admit model-screen runs, fetch their W&B summaries from the repository root:
`set -a && . ./.env && set +a && harness/.venv/bin/python report/analysis/model_benchmark.py --fetch --since <UTC time>`.
Only runs created at or after `--since` enter the snapshot, and only finished runs of
one condition enter the table. Set `featured` (a column name) or `condition`
(`{"cell": ..., "prohibited": ..., "party_auditor_offers": ...}`) in the snapshot to override the defaults:
the first column alphabetically, and the condition most finished runs share.
Its tests run with `python3 -m unittest test_model_benchmark` from `report/analysis/`.

### Regenerating the figures

The report has an isolated, locked Python environment. From the repository root:

```sh
UV_CACHE_DIR="$PWD/.tools/uv-cache" uv venv --python 3.12 .harness/report-venv
UV_CACHE_DIR="$PWD/.tools/uv-cache" uv pip sync \
  --python .harness/report-venv/bin/python report/requirements.lock
make -C report figures PYTHON="$PWD/.harness/report-venv/bin/python"
make -C report
```

This renders vector PDF and 300-dpi PNG figures from the committed safe snapshot.
Ordinary TeX builds use the included PDFs and require neither Python nor the
ignored original run directory. The snapshot records source hashes and the run
configuration; it excludes prompts, message bodies, private observations, and
credentials. Re-extract it from the original run only when admitting changed
evidence; see `analysis/baseline_figures.py --help`.

Means and sample standard deviations use the two episode observations, not the
14 votes or 42 juror pairs as independent replicates. Pale solid regions use the
mean's hue and represent one descriptive sample SD, not a confidence interval.
Identical rates have SD zero and their regions collapse. Cross-episode
consistency has only one episode comparison, so its SD is unavailable. Private
abuse rates are unavailable because `C0` provides no private opportunity.

## Status and conventions

This is an internal smoke report, with no submission venue or named author list.
The report date is fixed to October 25, 2026 in `preamble.tex`; the running header
labels it a baseline integration report. The supplied style owns page geometry and
header setup. Local overrides leave the uploaded file unchanged.

The [brief](../docs/reporting/paper-brief.md) admits only W&B run `m073at4i`
(`M0-C0-T0-R0-S0-E0`). The earlier free-route attempt `2vu0jc3u` exhausted its
daily quota and failed both episodes; it is an operational record, excluded from
the successful retry's behavioral means. Scripted, mock, historical, and former
fictional results are excluded. The 20-episode first pass and all treatment
comparisons remain future work. This is not a submission-ready empirical study.

## Changelog

### 2026-10-25

- Add six single-episode DeepSeek probes (X1–X6) as a bounded exploratory
  section. Each probe is one episode, so the report gives counts, not rates or
  spreads, and names the compared pairs and their code revisions. X2's auditor
  observations are excluded because a since-fixed defect showed the auditor both
  of each juror's offers as accepted. Probe numbers come from a content-free
  snapshot and a generated table so no interview text or reasoning is committed.

- Admit the two-episode baseline smoke and replace the fictional comparison.
  Use episode-level descriptive SD, preserve structural NAs, and retain the
  free-route failure separately so small-sample agreement cannot imply certainty.
- Commit safe figure inputs and vector PDFs so TeXShop and ordinary `make`
  builds remain portable without Python; regenerate assets explicitly with
  `make figures`. Keep a separate locked report environment to avoid changing
  harness dependencies.
- Keep `baseline_figures.py` scoped to its admitted run. New experimental results
  require an evidence-register update and corresponding validated inputs and
  analysis because its fixed run identity and two-episode assumptions belong to
  the baseline alone.
- Distinguish regenerating figures from replaying model behavior: the safe
  snapshot reproduces the plots, while provider nondeterminism and the original
  dirty working tree prevent claiming exact experiment replay from a clean revision.
- Select TeXShop's `pdflatexmk` engine and declare the root in every included
  TeX file so Cmd-T builds the complete manuscript and resolves references.
