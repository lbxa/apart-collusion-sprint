# Venue and submission record

**Project status: venue unselected.** A LaTeX research report is a main
deliverable; this guide does not commit the project to ICLR or any other venue.
Complete this record for the actual report before fixing its layout. Until
then, use the provisional [LaTeX defaults](latex.md).

## Current sample layout

The editable sample is [report/main.tex](../../report/main.tex), using the
user-supplied `arxiv.sty` unchanged as a general starting guide. This is an
**internal illustrative sample**, with no chosen submission venue or page limit.
The supplied style is not evidence of arXiv acceptance or compliance with a
conference's current requirements. Its attribution and attachment hashes are
recorded in [template provenance](../../report/template/README.md).

Build with `make -C report`: pdfLaTeX through `latexmk -pdf`, on US Letter with
6.5-inch text width and 9-inch text height from the style. The sample uses a
small keyed `thebibliography` in its own section file, with no external
bibliography pass. The document date is fixed in `report/preamble.tex`.
The [review record](../../report/review.md) records the tested toolchain and PDF
inspection. The submission fields below remain open for the actual venue.

## Required record

Replace `UNSET` with a verified value or an explicit `not applicable` plus a
reason. Keep the source URL and the date checked beside each external rule.

| Field | Project value |
| --- | --- |
| Venue, year, track, and paper type | UNSET |
| Document stage: internal / submission / rebuttal / camera-ready | UNSET |
| Official author guide and policy URLs; date checked | UNSET |
| Official template URL, release/version, download date, and checksum or committed revision | UNSET |
| Local report root and main `.tex` file | UNSET |
| Required class/style and review/final switches | UNSET |
| Compiler, TeX distribution, bibliography backend, exact build command | UNSET |
| Main-text page limit and what counts toward it | UNSET |
| References, appendices, supplementary material: placement and limits | UNSET |
| Paper size, margins, columns, fonts, and figure widths | UNSET |
| Citation and bibliography style; self-citation rules | UNSET |
| Anonymity: manuscript, PDF metadata, code/data links, supplements | UNSET |
| Required ethics, reproducibility, limitations, and AI-use disclosures | UNSET |
| Required data/code artifacts and accessibility requirements | UNSET |
| Submission files, size limits, portal, deadline, and stated timezone | UNSET |
| Camera-ready changes and publication/license requirements | UNSET |
| Last policy check, checker, and unresolved questions | UNSET |

Official rules for the chosen venue and stage take precedence over house
formatting. Preserve scientific accuracy and disclose limitations when fitting
the format. If official pages disagree, record the conflict and seek an
authoritative resolution; do not silently choose the convenient rule.

## ICLR 2027 example snapshot

This is a worked reference only. The
[official ICLR 2027 author guide](https://iclr.cc/Conferences/2027/AuthorGuidelines)
was inspected on **2026-10-25**. Its relevant headings state:

| Heading | Verified example requirement |
| --- | --- |
| Paper formatting | At submission, main text is at most 9 pages; discussion/rebuttal and camera-ready allow 10. References are excluded and unlimited. Appendices follow the bibliography and have no page limit; reviewers need not read them. |
| Style files and Templates | Use the [official 2027 LaTeX archive](https://media.iclr.cc/Conferences/ICLR2027/iclr-2027-style-files.zip) linked by the guide. |
| Double-blind submission and anonymity | Submission and supplementary material must be anonymous; related self-authored work is cited in third person. |
| Required: AI use statement | A mandatory AI-use section is excluded from the page limit. |

The separate [official AI policy for authors](https://iclr.cc/Conferences/2027/AIPolicyForAuthors),
under “Policy on LLM use for research and writing papers,” also requires
disclosure in the submission form and assigns responsibility for AI-assisted
content to the authors. Check its task-specific disclosure categories when
preparing a submission.

The archive URL was verified from the guide; its contents were not unpacked
or compiled for this snapshot. These entries do not establish template package
compatibility. Recheck all live rules and complete the project record before
using this example for an actual submission. Other tracks and years require
their own records. See [source notes](sources/latex-sources.md) and
[the review checklist](review.md).
