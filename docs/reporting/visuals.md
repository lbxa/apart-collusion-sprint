# Figures, tables, and diagrams

Use this guide with the [paper brief](paper-brief.md), [venue requirements](venue.md),
and [review checklist](review.md). Source editions, inspected sections, and concise
extractions are recorded in [visual source notes](sources/visual-sources.md).

The concrete sizes, palette, artifact records, and checks below are **house
standards**, implementing this project's reporting preferences. They are not
claimed as exact prescriptions from Rougier or the package manuals. Official
venue requirements take precedence; document any resulting exception.

## Decide what the reader should learn

Write one sentence describing the question each visual answers, and associate it
with a claim in the brief. Choose a plot for comparisons or patterns, a table for
exact values, and a diagram for relationships, geometry, or a process that is
hard to follow in prose. Use a short sentence when it communicates the result
adequately. Rougier's discussion starts with audience and message; it treats
readability as more important than decoration. [Rougier, “Ten simple rules,”
rules 1–2 and 9](sources/visual-sources.md#rougier-scientific-visualization).

## Figure specifications

| Element | Required house standard |
| --- | --- |
| Dimensions | Read the actual column and text widths from the chosen template. Generate at the intended physical width, rather than shrinking an oversized figure in LaTeX. Record width and height in the plotting script. |
| Typography | Use one font family consistently across figures, compatible with the report. Start with 9 pt axis labels and 8 pt tick/legend labels; no labels below 8 pt at final size unless a venue requires otherwise. Check mathematical glyphs and missing-font substitutions. |
| Strokes | Start with 1–1.5 pt data lines, 0.6–0.8 pt axes, and markers large enough to distinguish at final size. Adjust to the data density; retain distinguishable uncertainty boundaries. |
| Categorical color | Start with blue `#0072B2`, orange `#D55E00`, green `#009E73`, and purple `#CC79A7`. Keep each treatment's color stable throughout the report. Also distinguish series with markers, line styles, or direct labels. |
| Continuous color | Default to `viridis` for ordered magnitude. Use a diverging map only for a meaningful center, and state that center. Supply a labeled color bar and units. |
| Axes | Name quantities and units. Disclose log scales, transformations, broken axes, normalization, and omitted observations. Bars representing magnitude start at zero; use a point plot for comparisons needing a restricted scale. |
| Comparisons | Keep scales and ordering consistent across comparable panels. Explain intentional differences. Show the baseline and identify whether larger or smaller values are preferable. |
| Output | Prefer vector PDF for plots and diagrams. Rasterize dense layers when necessary while retaining vector labels. For raster images, use at least 300 dpi at final dimensions, or the venue's stricter requirement. |

The [Matplotlib style](templates/figure.mplstyle) provides a starting point;
scripts still need to set venue dimensions, semantic series mappings, and
appropriate plot types. Palette choice alone does not establish accessibility:
inspect the exported figure in grayscale and with a color-vision simulation.
If series merge, change the encodings or split the panels.

Rougier explains that figure typography should fit its publication context and
that colors should retain their meaning across figures. See the inspected
[typography and color chapters](sources/visual-sources.md#rougier-scientific-visualization).

## Captions and statistical interpretation

Every visual needs a caption and a reference from the main text. A caption must
identify the population or setup, treatment and comparator, metric and units,
sample size and denominator, and relevant exclusions or failures. Explain every
panel and encoding that readers need to interpret it.

For error bars or bands, state whether they represent SD, SE, a confidence
interval, a prediction interval, or another quantity. Give the interval level,
calculation method, and independent sampling unit. Repeated episodes from one
shared model or run are not automatically independent replicates. Put detailed
methods in the methods section and link them from the caption.

For this project, identify `core` versus `mock`, scripted versus model agents,
and historical versus newly generated results wherever that distinction affects
interpretation. Do not present a heuristic collusion flag as established
coordination. Keep simulated utility separate from contract settlement.

**Original illustrative caption — fictional experiment, not project evidence:**

> Figure X. Target-verdict rate under two model-agent treatments using the core
> backend. Points show 12/40 and 18/40 assigned attack trials; whiskers show 95%
> Wilson binomial intervals. Each trial uses an independently initialized
> episode with no shared memory. Infrastructure failures count as unsuccessful
> attacks and are reported separately: 2/40 and 1/40. These pilot results do not
> establish a difference between treatments.

The caption defines the endpoint, denominator, interval, independence assumption,
and failure handling, then limits the conclusion. Use the actual method and
independence structure of the experiment; do not inherit these fictional choices.

## Results tables

Use `booktabs` with `\toprule`, a heading separator `\midrule`, and `\bottomrule`.
Reserve `\cmidrule` for grouped headings. Ordinary results tables have no vertical
or double rules. Put units in headings, include leading zeros, and repeat values
instead of ditto marks. These rules follow [Fear, §§2–3](sources/visual-sources.md#fear-booktabs).

House checks: align numeric columns, use consistent precision within a metric,
and explain boldface or other emphasis. Distinguish missing, undefined, failed,
and zero values with an explicit legend. Include counts alongside rates when
denominators vary. Avoid scaling tables until their text is unreadable; simplify
headings, split the table, or use the appendix.

**Original illustrative table layout — fictional counts, not project results:**

| Treatment | Assigned trials | Target verdicts | Target-verdict rate (%) | Infrastructure failures |
| --- | ---: | ---: | ---: | ---: |
| A | 40 | 12 | 30.0 | 2 |
| B | 40 | 18 | 45.0 | 1 |

This Markdown sketch shows explicit denominators and uniform precision. The
LaTeX version should use the restrained rules demonstrated in the
[report example](templates/report-example.tex). Its caption must define how
failures enter the rate; avoid implying significance through bolding.

## Diagrams

Use TikZ when geometry, mathematical notation, or consistent LaTeX typography
benefits the explanation. Keep diagram source beside report source. For repeated
roles, define semantic styles such as `component`, `decision`, `dataflow`, and
`boundary` once, then reuse them. The manual demonstrates reusable styles in
[§2.8](sources/visual-sources.md#pgftikz-manual).

House checks: use the same shape for the same role, explain arrow direction and
line styles, and label information or control passed across important edges.
Keep crossings and abbreviations sparse. Make trust, authority, and observation
boundaries explicit when drawing the harness, API, and contract. A diagram must
agree with [the architecture](../architecture.md), not invent a second authority.

## Regeneration and final-size inspection

For each visual, retain the source script or TikZ file, input paths or run IDs,
filtering/aggregation choices, software environment, output path, and generation
command. Regenerate after changing inputs or analysis. Numerical table cells
must be traceable to the same saved outputs as their prose claims.

Inspect every exported visual **inside the compiled report at its final column
width**, then inspect the whole page. Check all labels, glyphs, clipping, contrast,
legends, captions, and panel order. Check that uncertainty remains visible and
that the visual agrees with the underlying values. Record issues and their
resolution in the [review record](review.md). Recheck after layout changes.
