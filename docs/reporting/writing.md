# Writing clear research reports

Apply these standards after completing the [paper brief](paper-brief.md).
They assume competence in routine LaTeX syntax. [Source notes](sources/writing-sources.md)
record the material actually consulted, its location, and access limits.
Rules below are project requirements; the citations identify their intellectual
basis, rather than implying that every source prescribes our exact workflow.

## Establish the reader and argument

1. **Specify the reader.** In the brief, record assumed knowledge, unfamiliar
   concepts, and what the reader should understand afterward. Check explanations
   against that record; author familiarity is insufficient evidence that a term
   is obvious. Pinker's [APS lecture abstract](sources/writing-sources.md#pinker)
   motivates this check.
2. **State the contribution early.** Give the report one central message. Make
   each supporting contribution specific enough to challenge, and point from it
   to the theorem, measurement, comparison, or case study that supports it.
   Establish the problem before presenting the solution; use an example before
   the general case when helpful. These requirements follow
   [Peyton Jones](sources/writing-sources.md#peyton-jones).
3. **Give each section and paragraph a job.** State the question a section
   answers and its main point once enough context is available. Each paragraph
   should develop one point through explanation, evidence, or qualification.
   Cut unrelated material or give it a separate home. This is house policy;
   [Williams and Bizup](sources/writing-sources.md#williams-and-bizup) provide
   further reading on framing and cohesion.

An abstract should identify the question, approach, main supported result, and
scope. Treat these as content requirements, not a mandatory sentence count.
Organize the report for the reader's understanding rather than the chronology
of the investigation. Required venue structure takes precedence; see
[venue.md](venue.md).

## Explain the mathematics

Apply these checks to every major definition, proposition, and derivation.
They adapt [Knuth, Larrabee, and Roberts, §1](sources/writing-sources.md#knuth-larrabee-and-roberts).

- Explain the need for a definition before introducing it; add an intuitive
  restatement or small example when the formal statement is difficult.
- Define every symbol on introduction, including its domain and relevant units.
  Use one notation for each concept and avoid reusing it for a different one.
- State theorem assumptions explicitly, so the result can be understood without
  reconstructing conditions scattered through surrounding prose.
- Connect equations with sentences explaining what follows and why. Read the
  prose with displays skipped: the argument's direction should remain apparent.
- Use complete sentences to introduce formal statements. Keep explanatory words
  between separate formulas, and avoid beginning sentences with bare symbols.

House policy: distinguish a definition, assumption, proved proposition,
empirical observation, and conjecture. Label which kind of statement is being
made. A derivation must show the step that matters scientifically, even if
routine algebra is abbreviated. Record notation conventions with the brief;
use [LaTeX guidance](latex.md) for implementation.

## Guide the reader through sentences

[Gopen and Swan](sources/writing-sources.md#gopen-and-swan) explain how sentence
structure guides interpretation. Use familiar context near the beginning;
place the intended emphasis where a clause closes. Keep the subject near its
verb, and express important actions in verbs. Link a new sentence to the
preceding idea before adding the next one. These are diagnostic tools requiring
judgment, not an algorithm or a ban on passive voice.

House checks:

- Prefer a visible actor and action: “We evaluated the model” is clearer than
  “An evaluation of the model was conducted” when responsibility matters.
- Keep technical terms stable; do not substitute synonyms for variety.
- Replace an ambiguous “this,” “it,” or “they” with its referent.
- Remove redundant wording while retaining conditions, uncertainty, and useful
  context. Shorter sentences are helpful only when their relationships remain
  clear.

## Make the reasoning inspectable

The publisher's [Craft of Research overview and contents](sources/writing-sources.md#the-craft-of-research)
distinguish claims, reasons, evidence, warrants, and objections. Our house
implementation is to record those relationships in the brief's claim-to-evidence
map and make the necessary connections visible in the report:

- Explain why the observation supports the conclusion and which assumption
  connects them. Identify a plausible alternative explanation or objection.
- Replace an unsupported “better,” “robust,” or “significant” with the measured
  comparison, quantity, and scope. Use “statistically significant” only with a
  specified inferential procedure and its result.
- Separate what was measured from the proposed mechanism. Present untested
  explanations as hypotheses and record missing evidence in the brief.
- Cite sources at the claim they support. Distinguish prior work from this
  project's contribution and describe relevant limitations fairly.

## Write figures with their results

Plan each chart with the paragraph it supports. State the question, observation
unit, metric, and warranted conclusion before choosing a display. Use the
[publication chart style](visuals.md#publication-chart-style) for Matplotlib
figures and the [mean and SD rules](visuals.md#mean-standard-deviation-and-small-samples)
for descriptive summaries. Keep detailed chart rules in that guide so prose and
plotting conventions have one source of truth.

Introduce every figure in the text and explain the observation the reader should
take from it. Captions must stand on their own: name the setting, panels, units,
sample size, denominators, mean/spread encoding, and relevant exclusions. With
small samples, distinguish the observed result from generalization; explain
zero or unavailable SD without implying certainty. Check numbers and labels
against the same admitted inputs used by the plot and results table.

## Annotated examples

All examples below are **fictional teaching examples**, written for this guide.
Their numbers and assertions are not project results or evidence.

### A motivated definition with an explicit condition

**Weak:** “Let \(r=k/n\). The rate is well defined.”

**Preferred:** “We need a rate that retains unsuccessful assigned trials in its
denominator. Let \(n>0\) be the number of assigned trials and \(k\) the number
meeting the prespecified success criterion. Define the assigned-trial success
rate as \(r=k/n\). Thus, a trial that fails before completion contributes to
\(n\), but not to \(k\).”

**Why:** The reader sees the measurement problem first. The symbols and
nonzero-denominator condition are explicit. The final sentence explains the
definition's practical consequence. The project's actual metric definition must
come from its brief and implementation.

### A concrete contribution without inflated inference

**Weak:** “Our method is significantly better and solves the problem.”

**Preferred:** “On the prespecified evaluation set, method B produced 16 errors
in 100 assigned trials, compared with 24 for method A: an observed reduction of
8 percentage points. Table 2 reports the trial counts and uncertainty analysis.
This comparison concerns the evaluated settings; it does not establish a general
advantage across tasks.”

**Why:** The comparison and denominator are visible. The evidence pointer makes
the claim checkable. The final sentence preserves scope; no significance test
or universal conclusion is invented. A real report must replace “Table 2” with
an automatic reference and provide the promised analysis.

### Visible action and a qualified explanation

**Weak:** “An analysis of failures was undertaken. This demonstrates the
effectiveness of coordination.”

**Preferred:** “We inspected the failed trials and found repeated identical
responses. Those repetitions are consistent with coordination, but shared
prompts could also explain them. Distinguishing these explanations requires a
control that varies prompt overlap.”

**Why:** The actor, observation, interpretation, alternative, and missing test
are separate and understandable. A suggestive pattern does not become proof.

## Revision pass

Read the abstract and introduction against the brief: do they promise exactly
what the report delivers? Then read one section as its intended audience,
marking missing definitions, unexplained transitions, and competing meanings.
Resolve those marks in the prose or record an evidence gap. Finish with the
[review checklist](review.md), including rendered-page and
[visuals](visuals.md) inspection.
