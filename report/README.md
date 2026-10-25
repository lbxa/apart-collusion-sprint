# Sample Veracity report

This is the illustrative report from the reporting guide, expanded into a
sectioned manuscript using the supplied `arxiv.sty` as a starting layout.
**All quantitative results are fictional teaching counts.** It contains no new
model experiment or claim of actual collusion. The system description cites
the repository documents it uses.

## Files

| File | Purpose |
| --- | --- |
| [main.tex](main.tex) | Main document; orders the section inputs |
| [preamble.tex](preamble.tex) | Packages, semantic macros, diagram styles, and template overrides |
| [arxiv.sty](arxiv.sty) | Supplied single-column style, preserved byte-for-byte |
| [Abstract](sections/abstract.tex) | Question, illustrative comparison, and scope |
| [Introduction](sections/introduction.tex) | Motivation and report aims |
| [Research environment](sections/system.tex) | Mechanism and system-boundary diagram |
| [Methods](sections/methods.tex) | Endpoint, notation, denominator, and uncertainty assumptions |
| [Results](sections/results.tex) | Fictional comparison, table, and figure |
| [Discussion](sections/discussion.tex) | Interpretation and limitations |
| [Conclusion](sections/conclusion.tex) | Supported takeaway |
| [References](sections/references.tex) | Keyed references to inspected local primary documents |
| [Makefile](Makefile) | Regenerates the figure, then compiles the whole document |
| [Template provenance](template/README.md) | Attachment attribution, hashes, and adaptation decisions |
| [Review record](review.md) | Build and rendered-PDF checks for this sample |

Only `main.tex` is a standalone document. Edit prose in `sections/`, keep common
formatting in `preamble.tex`, and change section order through `main.tex`.
The figure generator and style remain canonical in
[the reporting templates](../docs/reporting/README.md#table-of-contents).

## Build

From the repository root:

```sh
make -C report
```

Requirements: Make, Python with Matplotlib, `latexmk`, pdfLaTeX, and the standard
Geometry, Fancyhdr, T1 Times fonts, AMS, Booktabs, graphics, Microtype, TikZ, and
Hyperref packages. `PYTHON` and `LATEXMK` can select installed executables, for
example `make -C report PYTHON=/path/to/python`.

The PDF is **`report/build/main.pdf`**. The output directory also holds the TeX
log, figure PDF, figure provenance JSON, and temporary files; it is ignored by
Git. `make -C report clean` removes LaTeX build products and the report PDF.
Running `make` again regenerates the figure and rebuilds changed TeX sources.

For direct editor compilation, run `make -C report figures` first, then compile
`main.tex` from this directory with pdfLaTeX until cross-references stabilize.
The tiny bibliography uses `thebibliography`; it needs no BibTeX pass. A future
research bibliography can use the selected venue's backend and style.

## Status and conventions

This is an internal sample, with no submission venue or named author list.
The report date is fixed to October 25, 2026 in `preamble.tex`; the running header
labels it an illustrative sample. The supplied style owns page geometry and
header setup. Local overrides leave the uploaded file unchanged.

Follow the [reporting guide](../docs/reporting/README.md) for real manuscripts.
Before replacing the teaching counts, fill the brief's evidence and claim map,
choose actual treatment definitions, and regenerate figures and tables from the
admitted data. Keep counts and references consistent across abstract, methods,
results, table, figure, and conclusion. The sample is ready to edit; it is not a
submission-ready empirical report.
