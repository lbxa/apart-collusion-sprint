# Report review and completion

Use this checklist for each substantive draft and the final rendered PDF. Mark
items pass, fail, or not applicable with a reason and a locator. Record the
revision and output being reviewed. This is house policy applying the
[writing](writing.md), [visual](visuals.md), and [LaTeX](latex.md) standards;
source provenance is indexed in [the guide](README.md).

## Scientific support

- [ ] The [brief](paper-brief.md) identifies the reader, question, contribution,
  main result, and unresolved gaps. Every main contribution and important claim
  maps to a theorem, experiment, or other inspectable evidence.
- [ ] The argument explains why that evidence supports the conclusion and names
  required assumptions. Theorems state domains, quantifiers, and conditions;
  proofs cover cases used in the claim. Examples do not stand in for proofs.
- [ ] Counts, denominators, exclusions, failure rates, uncertainty methods, units,
  effect sizes, and baselines match the cited data and analysis revision.
  Repeated episodes or shared scenarios are handled with an appropriate unit of
  analysis. Undefined quantities are labeled, not plotted or tabulated as zero.
- [ ] Mean/SD summaries identify the eligible observation unit and sample size;
  sample SD uses `n - 1`. Nested votes, pairs, or rounds are not counted as extra
  independent replicates. Zero SD remains collapsed, SD with fewer than two
  observations is unavailable, and descriptive SD is distinguished from SE/CI.
- [ ] Backend, protocol version, deployment, model/prompt, treatment, observation
  access, and randomness are traceable. Mock, scripted, historical, and model
  results are labeled and not silently pooled. Scripted oracle performance is
  not a model result; a detector flag is not proof of collusion.
- [ ] Alternative explanations, negative results, limitations, and scope of
  generalization are visible. Causal language matches the actual design.
- [ ] Abstract, introduction, conclusion, captions, and numbers agree. No draft
  placeholder or illustrative example is presented as an observed finding.

## Reader comprehension

- [ ] Can the intended reader identify the question, contribution, and main result?
- [ ] Does understanding require an unstated definition or missing reasoning step?
- [ ] Could a reasonable reader interpret any important claim differently from
  what we mean? Resolve ambiguity in scope, comparison, uncertainty, and terms.
- [ ] Each section has a purpose; paragraphs support one main point. Definitions
  are motivated, symbols are introduced, and equations form connected prose.
- [ ] Actors and actions are clear; familiar context leads into new information.
  Stable terminology and explicit referents connect sentences. Editing preserves
  necessary conditions and uncertainty.

## References and submission rules

- [ ] Every cited work was checked against its source; authors, title, year,
  version, and bibliographic identifiers are accurate. No invented references.
- [ ] Cross-references are automatic, resolve to the intended object, and use
  useful labels. Every figure/table is discussed; equation numbers serve a use.
- [ ] The actual year/track/stage and official template are recorded in
  [venue.md](venue.md). Page limits, anonymity, supplementary material, required
  statements, accessibility, and AI-use rules have been rechecked at submission.
- [ ] Source credit and any reuse permissions are correct. The selected venue's
  requirements take precedence over house layout or package defaults.

## Regeneration, compilation, and rendered pages

- [ ] Regenerate every data-derived figure and table from the admitted inputs
  after results change; record exact commands and environment versions.
- [ ] Build from a clean output directory with the recorded compiler and
  bibliography tools. Repeat required passes until references stabilize. Save
  the command, exit status, and log path; a generated PDF alone is not success.
- [ ] Resolve compilation errors, undefined references/citations, missing files,
  duplicate labels, and missing glyphs. Inspect every overfull box. Resolve
  material layout warnings and document any accepted warning with a reason.
- [ ] Inspect **every rendered page** for clipping, bad breaks, float order,
  white space, equation margins, table overflow, and misplaced captions. Inspect
  figures at final column width and a normal viewing size; zooming in does not
  establish that labels are readable in the report.
- [ ] Axis labels, scales, units, legends, color encodings, uncertainty bands,
  and captions are interpretable. Color is not the only distinction. Tables use
  restrained rules and consistent precision. Diagrams label the intended
  relationships and have consistent styles.
- [ ] Charts follow the [publication style](visuals.md#publication-chart-style):
  manuscript-compatible typography, restrained colors, raw observations where
  useful, and lighter solid same-hue SD fills with visible mean marks. Axes,
  footnotes, panel titles, and captions have enough space at final print size.
- [ ] Vector chart fonts are embedded, PNG previews meet final-size resolution,
  and grayscale/color-vision checks preserve the meaning of markers and labels.
  The saved script, safe inputs, environment and command reproduce the figures.
- [ ] Review the actual submission PDF, including font embedding and file size
  if required by the venue. Check the supplement and any promised reproduction
  assets as well as the main text.

For the included example, follow [the preview commands](README.md#preview-the-reusable-example).
For the actual manuscript, record its own commands; the example does not select
a venue, pin the future report's toolchain, or validate project findings.

## Review record

Store a completed copy with the report or run artifacts and link it from the
brief. Leave unresolved items visible; a draft may carry gaps, but a report with
unresolved required checks must not be marked submission-ready.

```text
Review date / reviewer:
Source revision / dirty changes:
Manuscript path / PDF path:
Venue, year, track, stage / rules checked at:
Evidence IDs and analysis revision:
Figure/table regeneration commands and output paths:
Compiler / distribution / package and bibliography versions:
Clean build command / exit status / log:
Pages and figures inspected at final size:
Scientific and reader-comprehension findings:
Accepted warnings / not-applicable checks and reasons:
Open gaps / responsible person / next action:
Decision: draft | revision required | submission-ready
```
