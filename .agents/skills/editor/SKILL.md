---
name: editor
description: Write, revise, and review the Collusion Sprint research manuscripts in report/. Use for report structure, prose, mathematical exposition, methods, results, captions, and evidence-backed conclusions.
---

# Editor

Act as the report's chief editor. Write for an independent research reader who
has not followed the experiment chats. **Choose clarity over brevity.** Explain
what makes an argument work without repetition or inflated claims.

Apply this standard during report writing and review even when the user does
not ask for a separate editorial pass. Read [AGENTS.md](../../../AGENTS.md),
the [report README](../../../report/README.md), and the relevant manuscript
README. Then follow the [reporting guide](../../../docs/reporting/README.md):
brief, venue, writing, visuals/LaTeX, and review. Venue rules govern formatting;
the brief governs the claims admitted by the evidence.

## Edit the manuscript that owns the evidence

The active manuscript is [report/agentic/main.tex](../../../report/agentic/main.tex).
Build it with `make -C report agentic` and record checks in its
[review record](../../../report/agentic/review.md). The October agentic snapshot
builds with `make -C report agentic-historical`. The older baseline builds with
`make -C report`. Preserve each manuscript's provenance and evidence scope.

Use the layout, section and disclosure requirements in the
[venue record](../../../docs/reporting/venue.md), including the Limitations and
Dual-Use / Ethical Considerations appendix. Preserve confirmed author metadata
and flag open disclosure or template-compliance issues during review.

As cloud experiment evidence arrives, update the brief's claim-to-evidence map
before strengthening the report. Keep methods, results, discussion, limitations,
and captions consistent with the same frozen evidence selection. Draft only
what is supported now and leave unresolved questions explicit. Preserve
concurrent edits by reading the latest files and diff before changing them.

## Write the reasoning in full

- Use complete sentences and connected paragraphs. Let equations participate
  in grammatical sentences. State the question, approach, and supported result
  early once evidence exists.
- Define notation, domains, units, hypotheses, and the observation unit before
  use. Explain why a theorem or statistical method applies. Spell out the bridge
  between steps instead of hiding it behind "clearly" or a chain of implications.
- Make assumptions, choices, and dependencies visible. Distinguish definitions,
  proved results, observations, interpretations, and untested hypotheses.
- Keep essential justifications in the body. Optional asides and appendices
  may expand the argument but must not hide the premise needed to understand it.
- Preserve valid author reasoning and established terminology. Repair gaps
  locally rather than replacing an argument merely to impose a different style.

## Build intuition without weakening the evidence

Explain the mechanism and its purpose, then connect it to the formal statement
or experimental design. Use a worked example or diagram when it resolves a real
obstacle. Label illustrations and scripted controls so they cannot be mistaken
for model behavior. A selected trajectory is not a population estimate, and
provider-returned reasoning is not independently verified internal computation.

For empirical claims, state the measured comparison, denominator, failures,
exclusions, and uncertainty. Repeated cases, jurors, and rounds are not extra
independent runs. Follow the [benchmark](../../../docs/benchmark.md) for label
admission. Separate proposals, agreements, implementing actions, compromised
outcomes, obligation violations, and capability errors. Preserve assigned cases,
unresolved labels, and the distinction between confirmation and exploratory
recovery. Adverse settlement and confirmed payout establish mechanical outcomes.
Claims of knowing or executed harmful coordination require the corresponding
reviewed evidence. Match causal language to the actual intervention.

## Make the report flow

Organize for the reader's understanding rather than execution chronology.
Introduce prerequisites before substantial use. Give each section a question
and each paragraph one main point. Link adjacent sections through their
scientific relationship. Keep terminology and notation stable across prose,
equations, tables, figures, and abstract.

Keep operational handoffs, raw transcript inventories, and investigation
progress in the campaign records. Include the methods and provenance needed to
evaluate and reproduce the research, without making the paper an operations log.
Verify citations against retrievable sources and place them beside the claims
they support. Do not invent references, results, author affiliations, or approvals.

## Write visuals with their interpretation

Follow [visuals.md](../../../docs/reporting/visuals.md) for quantitative plots,
tables, and diagrams. Give every figure a question, caption, stable label, and
nearby body reference. Captions should identify the setting, units, sample size,
uncertainty, and relevant exclusions. Regenerate tables and figures from admitted
versioned artifacts and recorded analysis, never from manually typed results.

Use TikZ when source-defined geometry helps explain the system. Match labels
to what is actually drawn and keep annotations readable at final size. Give
crowded content more room rather than shrinking type to disguise the problem.

## Preserve consistency and review honestly

Use the manuscript's shared preamble, semantic notation, automatic references,
and bibliography backend. Follow the actual venue's style when selected. Do
not import textbook margin components, homework workflows, or review wrappers
that this project does not implement. Preserve any real author review status.

Before finishing, read the changed passage continuously, check scientific and
mathematical correctness separately, build the affected manuscript, and inspect
rendered pages at final size. Check overflow, float order, captions, labels, and
references. Record the build and editorial review with remaining gaps according
to [review.md](../../../docs/reporting/review.md). A clean compile alone does not
establish editorial quality, scientific support, or submission readiness.
