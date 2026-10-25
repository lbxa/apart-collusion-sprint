# Sample report review

Reviewed **2026-10-25** against [the reporting checklist](../docs/reporting/review.md).
Decision: **ready as an illustrative sample**; not an empirical submission.

## Artifact and toolchain

| Field | Recorded value |
| --- | --- |
| Source | [main.tex](main.tex), [preamble.tex](preamble.tex), and `sections/*.tex` |
| Repository baseline | `bd79b5c` plus the reporting-guide and sample-report commits; refreshed against the private-chat API, generated Python client, and current collector before merge |
| PDF | [build/main.pdf](build/main.pdf), 3 pages on US Letter |
| Stage and venue | Internal illustrative sample; venue unselected |
| Template | Uploaded `arxiv.sty`, unchanged; hashes and attribution in [template provenance](template/README.md) |
| TeX engine | pdfTeX 3.141592653-2.6-1.40.26, TeX Live 2025/dev/Debian |
| Build driver | Latexmk 4.86, December 11, 2024 |
| Figure environment | Python 3.12.14; Matplotlib 3.10.8 |
| Bibliography | Keyed `thebibliography`; no external backend |
| Package versions | Recorded by `\listfiles` in `build/main.log` |
| Clean TeX build | `make -C report clean`, then `make -C report`; exit status 0 |
| Figure regeneration | `make -C report figures`; canonical script `docs/reporting/templates/figure-example.py` |
| Figure provenance | `build/figures/figure-example.json`; 3.35-inch width; counts 12/40 and 18/40; failures 2 and 1 |

## Review findings

- **Scientific scope — pass for a sample.** Every quantitative comparison is
  explicitly fictional. The local system references support the architecture
  description; none is presented as evidence for the invented counts. The
  method defines its endpoint, assigned-trial denominator, notation, failure
  treatment, and illustrative independence assumption. The text makes no
  significance, causal, or actual-collusion claim.
- **Argument and consistency — pass.** The question, numerical comparison, and
  limitations agree across abstract, methods, results, table, plot, and
  conclusion. The arithmetic difference is 15 percentage points. Uncertainty
  bars are identified as marginal 95% Wilson intervals, not a contrast test.
- **Template and organization — pass.** Only `main.tex` is a standalone
  document. Each paper section is a separate TeX input. The supplied style and
  README match their attachment hashes. Template content was used as reference
  material; its sample authors, subject matter, and old submission advice were
  not adopted as project requirements.
- **Build and references — pass.** A fresh TeX build stabilized cross-references
  and citations. The final log has no LaTeX/package warnings, overfull/underfull
  boxes, undefined references/citations, or missing glyphs. All PDF fonts are
  embedded; the preamble selects vector Courier for monospace paths.
- **Rendered pages — pass.** Inspected all three final pages for clipping,
  equation alignment, heading breaks, float order, tables, captions, and
  reference placement. The bibliography fits on the final page. Inspected the
  plot at its final 3.35-inch width and in grayscale; shapes preserve treatment
  distinctions and labels remain readable.
- **Independent source review — pass.** A separate agent reviewed paths, style
  compatibility, provenance, and scientific scope, finding no unresolved issue.
- **Repository verification — pass.** After sourcing `.tools/cloud-env.sh`,
  `bash scripts/verify.sh` exited 0. Hook checks, 32 Solidity tests including
  fuzz/invariants, Rust formatting/Clippy/tests/builds, generated schema/client
  drift checks, Python regressions, and the harness scenario suite passed. Run log:
  `/tmp/veracity-report-merge-verification.log`.

## TeXShop compatibility recheck — 2026-10-25

Source baseline: `641b5c0` plus the report compatibility changes. Scientific
content and the supplied style are unchanged. The original review above
records the earlier Linux build; the following checks cover the local Mac.

- **Reproduction.** A fresh copy of the saved sources failed direct pdfLaTeX
  compilation because `figure-example.pdf` existed only after running the
  Make figure target. The reported disappearing `main.aux` was not reproduced
  from those saved sources. The old TeXShop run was stopped at its filename
  prompt before retesting.
- **Package fix.** The generated vector figure is now included in `figures/`.
  Ordinary builds need only TeX; `make figures` explicitly regenerates the
  included asset and saves provenance in `build/figures/figure-example.json`.
  `main.tex` selects `pdflatexmk`; all included TeX files declare their root.
- **Local toolchain.** TeXShop 5.49; pdfTeX
  3.141592653-2.6-1.40.27 (TeX Live 2025); Latexmk 4.86a. Figure regenerated
  with Python 3.12.11 and Matplotlib 3.11.2 using
  `make -C report figures PYTHON=/path/to/python`. The asset remains a
  3.35-inch vector figure with the same fictional counts and Wilson intervals.
- **Editor build — pass.** Opened `main.tex` in TeXShop and used Cmd-T. The
  installed `pdflatexmk` engine completed, recreated `main.aux` and SyncTeX,
  resolved all references, and displayed the three-page `main.pdf`. The final
  `main.log` contains no warnings, overfull/underfull boxes, or missing glyphs.
- **Clean and portable builds — pass.** `make -C report` completed with exit
  status 0; log: `/tmp/veracity-texshop-make.log`. A fresh report-only copy in
  a directory containing spaces compiled with the installed TeXShop engine
  without a figure-generation step; log: `/tmp/veracity-texshop-portable.log`.
  In that copy, `make clean` removed editor/build outputs and retained the
  figure, then `make PYTHON=/nonexistent/python` succeeded; logs:
  `/tmp/veracity-texshop-clean.log` and
  `/tmp/veracity-texshop-clean-rebuild.log`. The LaTeX compile skill also
  resolved `sections/results.tex` to `main.tex` and compiled successfully;
  result: `/tmp/veracity-texshop-section-build.json`.
- **Rendered pages — pass.** Re-rendered and inspected all three local PDF
  pages at 90 dpi, including the diagram, equations, table, figure at its
  retained width, and bibliography. No clipping, overlap, broken references,
  or unreadable labels found. Page images: `/tmp/veracity-texshop-pages/`.
- **Repository verification — pass.** `bash scripts/verify.sh` exited 0 after
  rerunning with local test execution permitted. The sandboxed attempt timed
  out starting Anvil; no chain tests were skipped. Successful run log:
  `/tmp/veracity-texshop-repository-verification-unrestricted.log`.

Decision: ready for local TeXShop editing as an illustrative sample. The
empirical manuscript gaps below remain open.

## Open work for the empirical manuscript

No real experiment is admitted here. Treatment definitions, run evidence,
model and prompt settings, statistical analysis, actual authors, and a submission
venue remain to be established in the [paper brief](../docs/reporting/paper-brief.md)
and [venue record](../docs/reporting/venue.md). Venue-specific page limits,
anonymity, and submission disclosures are not applicable to this internal sample.
Re-run this review after replacing its teaching content or changing its layout.
