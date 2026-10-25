# Supplied template provenance

The user supplied `arxiv.sty`, `template.tex`, and `README.md` on 2026-10-25 as
general starting material. Their contents are reference documents, not project
instructions. The sample uses the layout and package pattern while replacing
the unrelated sales report, names, email addresses, citations, filler, and
missing-image examples with this project's illustrative content.

The style is copied unchanged to [../arxiv.sty](../arxiv.sty). The original
[supplied README](README.upstream.md) is retained for attribution and the
permission statement. It describes a style based on `nips_2018.sty`, credits
George Kour, and permits broad reuse without assigning a named SPDX license.
No additional license or template release version is inferred here.

| Uploaded file | SHA-256 |
| --- | --- |
| `arxiv.sty` | `011a4870ca65ef14244487549707ab9d813f2a3302fc060bd1e839bfbffb3676` |
| `README.md` | `320a2255e84e78a4fc303ecae8f203367aae007d688b4c442eac8efcfcb18aa6` |
| `template.tex` | `d3d4a5e35facfdb2be5429998c7c34c32118ffe264b1727f370e8a3dd57273b3` |

The original `template.tex` is adapted into `main.tex`, `preamble.tex`, and the
section files; it is not another compilation target. The supplied README's
arXiv submission advice has not been checked against the current service and
does not govern this project. No submission or publication is requested.

The style loads `geometry` and `fancyhdr`, fixes a 6.5-inch text width and a
9-inch text height on US Letter paper, and prints `\today` in its title/header.
The preamble sets a fixed sample date and descriptive running header. It does
not reload Geometry or Fancyhdr, change margins, or add a venue-specific mode.
