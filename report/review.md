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

## Open work for the empirical manuscript

No real experiment is admitted here. Treatment definitions, run evidence,
model and prompt settings, statistical analysis, actual authors, and a submission
venue remain to be established in the [paper brief](../docs/reporting/paper-brief.md)
and [venue record](../docs/reporting/venue.md). Venue-specific page limits,
anonymity, and submission disclosures are not applicable to this internal sample.
Re-run this review after replacing its teaching content or changing its layout.
