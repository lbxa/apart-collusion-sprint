# Venue and submission record

**Project target: Apart AI Collusion Research Sprint, October 23–25, 2026.**
The user selected this sprint as the target. The separate
[agentic manuscript](../../report/agentic/main.tex) is an internal results draft;
the older baseline report remains unchanged. A submission-ready revision must
meet the verified requirements below.

## Apart sprint requirements, checked 2026-10-26

The [official guidelines](https://apartresearch.com/sprints/ai-collusion-research-sprint-2026-10-23-to-2026-10-25)
require a PDF using the linked official template, at most eight main-text pages
excluding references and appendices, a 150–250-word abstract, author names and
affiliations, and a Limitations and Dual-Use / Ethical Considerations appendix.
Methods should identify models, prompts, environment, seeds and metrics; results
should include baselines, seeds, variability and a positive control. Existing
work and work completed during the sprint must be distinguished.

The official template link points to [this Google document](https://docs.google.com/document/d/1Y5wd3VRbXU5N08BvAGiJUQTaWbMCSPjhzXsR-ozuehg/copy?usp=sharing).
Its text was read through the connected Google Drive account after the browser
copy link redirected to sign-in. The template recommends four pages and allows
adapting its section structure: Introduction, Related Work, Methods, Results,
Discussion and Limitations, Conclusion, Code and Data, References, and an LLM
Usage Statement. The live guideline's eight-page cap remains controlling.
The template was last modified 2026-10-22. Its visual layout has not been
inspected; the current `arxiv.sty` is not verified as a layout substitute.

The published deadline is 2026-10-25 at 23:59 Anywhere on Earth (UTC−12), which
is 2026-10-26 at 07:59 in America/New_York (EDT). Submission is not authorized
by the research task and has not been attempted.

## Current report layouts

The agentic manuscript uses `article` at 11pt on US Letter, one-inch margins
and New TX text/math fonts. Build `make -C report agentic` with TeX Live
pdfLaTeX through latexmk; the PDF is `report/agentic/build/main.pdf`.
Its main text is followed by references, the limitations/ethics appendix,
and a complete run/episode appendix. The
[review record](../../report/agentic/review.md) preserves checks and gaps.
The user requested removal of its LLM Usage and Execution/accounting
appendices. This edit does not certify final submission compliance.

The editable sample is [report/main.tex](../../report/main.tex), using the
user-supplied `arxiv.sty` unchanged as a general starting guide. This is an
**internal baseline integration report**. Its two-episode live smoke evidence
replaces the earlier fictional teaching comparison; it is not the agentic
sprint manuscript.
The supplied style is not evidence of arXiv acceptance or compliance with a
conference's current requirements. Its attribution and attachment hashes are
recorded in [template provenance](../../report/template/README.md).

Build with `make -C report`, or open `report/main.tex` in TeXShop and typeset
with its selected `pdflatexmk` engine: pdfLaTeX through `latexmk -pdf`, on US
Letter with 6.5-inch text width and 9-inch text height from the style. The sample uses a
small keyed `thebibliography` in its own section file, with no external
bibliography pass. The document date is fixed in `report/preamble.tex`.
The vector figures are included in `report/figures/`; regenerate them explicitly
with `make -C report figures` when their sources change.
The [review record](../../report/review.md) records the tested toolchain and PDF
inspection. The submission fields below remain open for the actual venue.

## Required record

Replace `UNSET` with a verified value or an explicit `not applicable` plus a
reason. Keep the source URL and the date checked beside each external rule.

| Field | Project value |
| --- | --- |
| Venue, year, track, and paper type | Apart AI Collusion Research Sprint 2026, research report |
| Document stage: internal / submission / rebuttal / camera-ready | Internal results draft |
| Official author guide and policy URLs; date checked | Official sprint URL above; 2026-10-26 |
| Official template URL, release/version, download date, and checksum or committed revision | Linked Google document above; text inspected, modified 2026-10-22; visual compliance unresolved |
| Local report root and main `.tex` file | `report/agentic/main.tex` |
| Required class/style and review/final switches | Official template required; current article draft not certified equivalent |
| Compiler, TeX distribution, bibliography backend, exact build command | pdfLaTeX, TeX Live 2025, latexmk 4.86a; inline bibliography; `make -C report agentic` |
| Main-text page limit and what counts toward it | Eight main-text pages excluding references/appendices; abstract 150–250 words |
| References, appendices, supplementary material: placement and limits | References then required limitations/ethics appendix; no separate verified supplement cap |
| Paper size, margins, columns, fonts, and figure widths | Current draft: Letter, 1in margins, one column, 11pt New TX, 6.5in figure; official visual requirements unresolved |
| Citation and bibliography style; self-citation rules | UNSET |
| Anonymity: manuscript, PDF metadata, code/data links, supplements | UNSET |
| Required ethics, reproducibility, limitations, and AI-use disclosures | Required limitations/dual-use/ethics appendix present; template includes LLM usage statement removed at user request; final author review open |
| Required data/code artifacts and accessibility requirements | UNSET |
| Submission files, size limits, portal, deadline, and stated timezone | PDF; deadline above; no submission attempted; remaining portal/size details unverified |
| Camera-ready changes and publication/license requirements | UNSET |
| Last policy check, checker, and unresolved questions | 2026-10-26, Codex; authors Lucas Barbosa, Stefan Gazana, Sravika Linga, Muskaan Kumar, Jake Fogel; affiliations, visual layout and final disclosures open |

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
