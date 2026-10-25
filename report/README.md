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
| [Figure PDF](figures/figure-example.pdf) | Included vector figure for direct editor compilation |
| [Makefile](Makefile) | Compiles the document; regenerates the figure on request |
| [Template provenance](template/README.md) | Attachment attribution, hashes, and adaptation decisions |
| [Review record](review.md) | Build and rendered-PDF checks for this sample |

Only `main.tex` is a standalone document. Edit prose in `sections/`, keep common
formatting in `preamble.tex`, and change section order through `main.tex`.
The figure generator and style remain canonical in
[the reporting templates](../docs/reporting/README.md#table-of-contents).

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
preserving the included figure. Run cleanup only when no build is active.

### Regenerating the figure

When the illustrative plot changes, run `make -C report figures` with Python
and Matplotlib installed. `PYTHON` selects the interpreter, for example
`make -C report figures PYTHON=/path/to/python`. This regenerates the canonical
plot and its provenance JSON in `build/figures/`, then updates the included
`figures/figure-example.pdf`. Include that PDF with source changes so editor
builds remain self-contained. Ordinary builds do not regenerate the figure.

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

## Changelog

### 2026-10-25

- Include the vector figure with the report so TeXShop and ordinary `make`
  builds work without a Python environment; regenerate it explicitly with
  `make figures` when its source changes.
- Select TeXShop's `pdflatexmk` engine and declare the root in every included
  TeX file so Cmd-T builds the complete manuscript and resolves references.
