# Visual standards: inspected sources

Inspected **2026-10-25**. These are concise paraphrases, not reproductions of the
works. The operational house standards are in [visuals.md](../visuals.md).
Package APIs remain available for lookup; the source principles below are saved
so routine report work does not depend on reopening links.

## Rougier: Scientific Visualization

- **Work:** Nicolas P. Rougier, *Scientific Visualization: Python + Matplotlib*,
  November 2021. [Author repository](https://github.com/rougier/scientific-visualization-book).
- **Snapshot:** repository HEAD resolved to
  `62fa569f30333c817c13e4dc757877c1192fd15a` on the inspection date. Pin chapter
  links to that revision when checking the extracted guidance.
- **Read:** [“Ten simple rules”](https://github.com/rougier/scientific-visualization-book/blob/62fa569f30333c817c13e4dc757877c1192fd15a/rst/rules.rst),
  especially rules 1–9; [“Elements of typography”](https://github.com/rougier/scientific-visualization-book/blob/62fa569f30333c817c13e4dc757877c1192fd15a/rst/typography.rst),
  opening discussion and “Font stacks”; [“A primer on colors”](https://github.com/rougier/scientific-visualization-book/blob/62fa569f30333c817c13e4dc757877c1192fd15a/rst/colors.rst),
  “Choosing colors”; [“Mastering the defaults”](https://github.com/rougier/scientific-visualization-book/blob/62fa569f30333c817c13e4dc757877c1192fd15a/rst/defaults.rst),
  “Explicit settings” and “User settings.”
- **Extraction:** decide audience, message, and display medium before selecting
  a design. Explain a figure through its caption. Tune defaults to the task;
  misleading scales and unnecessary decoration can obscure results. Keep visual
  encodings consistent and select color maps appropriate to the data. Typography
  should fit the publication, with a coherent font family. Centralized defaults
  make styling repeatable.
- **Attribution:** the rules chapter credits Rougier, Michael Droettboom, and
  Philip E. Bourne and identifies its earlier PLOS article. The numerical font
  sizes, palette, and review requirements in our guide are house choices.

## Fear: Booktabs

- **Work:** Simon Fear, *Publication quality tables in LaTeX*,
  `booktabs` v1.61803398, revised 2020-01-12; PDF printed 2020-01-14.
  [CTAN package](https://ctan.org/pkg/booktabs),
  [inspected PDF](https://tug.ctan.org/macros/latex/contrib/booktabs/booktabs.pdf).
- **Read:** §§1–3, printed pp. 1–4, especially §2 “The layout of formal tables.”
- **Extraction:** formal tables should communicate through labeled columns and
  spacing. Omit vertical and double rules. Put units in headings, precede decimal
  points with a digit, and avoid ditto signs. Use the package's top, middle,
  bottom, and partial rules to express the table's hierarchy without a full grid.
- **Lookup:** later sections cover special cases and implementation. Our guide
  adds explicit missing-value semantics and experiment denominators as project
  requirements.

## PGF/TikZ manual

- **Work:** Till Tantau and the PGF/TikZ team, *TikZ and PGF Manual*.
  [CTAN package](https://ctan.org/pkg/pgf) reported version **3.1.12** on the
  inspection date. This is package metadata, not a claim that the HTML mirror
  below has the same build version.
- **Read:** manual content through the [HTML rendering](https://tikz.dev/tutorial),
  §2.8 “Adding a Touch of Style,” and
  [§7 “Guidelines on Graphics”](https://tikz.dev/guidelines), especially §§7.2–7.5.
- **Extraction:** establish what a graphic should communicate, draft its
  structure, and revise it alongside the text. Stand-alone figures need context
  in captions and references in the prose. Generate at the intended size and
  keep typography and visual encodings consistent. Named TikZ styles let related
  elements and multiple diagrams share a changeable appearance.
- **Access limitation:** CTAN's manual-PDF redirect failed in the web reader;
  the cited HTML manual sections were accessible and read. Use the
  [official manual link](https://mirrors.ctan.org/graphics/pgf/base/doc/pgfmanual.pdf)
  for full reference. We have not verified its complete current PDF or every
  feature in version 3.1.12.

## Maintaining these notes

When updating a rule, inspect the relevant primary-source passage and record its
edition or revision and section. Distinguish changes to the source from deliberate
house-style changes. Keep concise paraphrases here; retain detailed drawing and
plotting syntax in the manuals and the project's executable examples.
