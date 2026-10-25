# LaTeX conventions

Use this with [writing](writing.md), [visuals](visuals.md), and the selected
[venue record](venue.md). Routine syntax is assumed. The source locators and
access boundaries are in [LaTeX source notes](sources/latex-sources.md).

## Equations and references

The following requirements adapt the AMS *Short Math Guide*, v2.0,
[§§2.1–2.2, 3.15, 4.5, and 7](https://tug.ctan.org/info/short-math-guide/short-math-guide.pdf).

- Use `equation` for one numbered display, `align` for aligned equation groups,
  and `split` inside `equation` for one number across several lines. Avoid
  `eqnarray` and plain-TeX `$$` displays.
- Use `\label` and `\eqref` for equations; let LaTeX maintain numbering. Use
  `\ref` or the template's compatible reference commands for other objects.
- Use named operators such as `\log`, or declare new operators with
  `\DeclareMathOperator`. Use `\text{...}` for prose inside mathematics.
- Let mathematical symbol classes supply ordinary spacing. Introduce manual
  spacing only to resolve a specific typographical need.

House conventions add these observable requirements:

- Record the meaning, domain, units, and indexing of each important symbol in
  [the paper brief](paper-brief.md). Introduce symbols in the text before use;
  distinguish population quantities from estimators.
- Treat a display as part of its sentence: introduce its purpose, punctuate it
  appropriately, and explain its implication. A chain of equalities must not
  conceal an assumption or an approximation.
- Use descriptive label prefixes (`eq:`, `sec:`, `fig:`, `tab:`, `thm:`).
  Place figure/table labels after captions. Never type a reference number by hand.
- Define recurring mathematical concepts through a small set of semantic
  macros in one preamble file. Avoid redefining standard commands.
- Cite through bibliography keys. Check each bibliographic record against the
  source; a successful compilation does not establish that a citation is real
  or supports the surrounding claim.

## Compiler and packages

These are provisional house defaults, not an existing project toolchain or a
claim about the requirements of any conference. Record the actual choices in
[venue.md](venue.md) when creating the report.

| Decision | Default until the chosen template specifies otherwise |
| --- | --- |
| Compiler | pdfLaTeX, driven by `latexmk -pdf` |
| Core mathematics | `amsmath`; add `amssymb` and `amsthm` when needed |
| Figures and tables | `graphicx`, `booktabs`; TikZ only for diagrams that benefit from source-defined geometry |
| Links | `hyperref` when compatible; respect the template's existing options and load order |
| Bibliography | Use the venue's backend and style; for an unconstrained new report, record the selected backend before adding citations |
| Reproducibility | Record TeX distribution/version, engine/version, build command, bibliography backend, and added package versions |

Start a submission from its official template. Retain its class, margins,
font setup, citation style, and review/final switches. Add packages only for
an actual need and check compatibility before adding overlapping formatting
packages. Do not use spacing hacks or smaller fonts to satisfy a page limit.

The [example report](templates/report-example.tex) demonstrates the house style
for an unconstrained report; it is not a venue template. Follow the
[complete preview commands](README.md#preview-the-reusable-example) to generate
its required figure and compile from a scratch directory. Keep generated files
outside the tracked source tree.

For the eventual report, replace the filename/output path and save its exact
build command with its source. Build until references and citations stabilize.
Resolve errors, undefined references/citations, missing glyphs, and clipped
content before calling the PDF ready. Review remaining warnings individually.
Inspect the rendered pages using [review.md](review.md).

## Deeper lookup

The freely available [Companion chapter samples](https://www.latex-project.org/help/books/tlc3-digital-chapter-samples.pdf),
Part I, Chapter 2, pp.21–24, describe the separation of document structure from
layout and the role of classes, packages, and the preamble. Keep these concerns
centralized so revisions apply consistently. Consult *The LaTeX Companion*,
third edition, for a specific technical problem; consult the installed
package manual for version-specific behavior. The full paid book was not used
as evidence for these standards.
