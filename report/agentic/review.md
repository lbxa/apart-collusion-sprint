# Agentic report review

Review date: 2026-10-26. Reviewer: Codex; not independent human review.
Report source: working changes on revision `f9a8ecc`. Experiments recorded
revision `11f4f01` plus per-run source hashes in
`report/data/agentic-campaign.json`, which distinguish runtime versions.
Manuscript: `report/agentic/main.tex`. PDF: `report/agentic/build/main.pdf`.
Decision: internal results draft; not submission-ready.

## Evidence and interpretation

- A0–A3 and AC1–AC4 are recorded in the reporting brief. All 13 runs and 19
  assignments are retained, including the interrupted pilot. Eighteen terminal
  episodes reconcile with engine evidence; seven strong, three ambiguous and
  eight not-established annotations are counts, not an incidence estimate.
- Strong-case reviews require actual-claim support, acknowledged adverse
  agreement before funding, executed votes, coalition benefit and outsider loss.
  Annotations pin exact source hashes; none is an independently human-validated
  label. Unchanged reference labels do not score changed submitted claims.
- Principal post-fix clear-case seeds 31 and 43 each have a communication-on
  and communication-off run. The earlier seed-31 pilot is not a third seed.
  Three-episode memory blocks are dependent observations, one block per cell.
- Local Anvil base units are not dollars. Contract-valid actions can harm
  factual adjudication. Honest safe payoff is zero in this stress case;
  positive productive honest returns and verification effort are not modeled.
- The user authorized publishing this complete campaign to the repository.
  Large source trajectories and checkpoints use Git LFS. Every combined
  experiment JSON parses; the 807-member raw archive passes CRC verification.
  Known configured secret values and credential patterns were checked across
  source files and archive entries without finding a match.

## Build and rendering

The native Codex compiler reported success. The independent reproducible build
uses TeX Live 2025 pdfLaTeX through latexmk 4.86a:

```sh
make -C report agentic
make -C report agentic-figures PYTHON="$PWD/.harness/report-venv/bin/python"
```

The PDF has no undefined references/citations or overfull boxes after repairing
a path line break. Main document fonts are embedded. Abstract: 202
words. Vector figures use the report's STIX/Times-compatible locked Matplotlib
environment and numeric safe snapshot; observed cells have text labels as well
as colors. No SD/CI is appropriate for the case-study display.

The original six rendered pages and the figure were inspected at final width. Poppler
was unavailable; Ghostscript rendered pages at 120 dpi and pypdf checked text
and font embedding. After the requested appendix removal, the PDF was rebuilt,
the deleted headings were confirmed absent, and the changed end pages were
rendered again. Build diagnostics are in `build/main.log`; rendered pages are
in `build/pages/`. These outputs are ignored.

The complete-results revision names Lucas Barbosa, Stefan Gazana, Sravika Linga,
Muskaan Kumar and Jake Fogel, in that order, in the title block and PDF metadata.
It adds the full 13-run inventory, a qualitative account of each run, and an
appendix covering all 19 assignments. The tables were reconciled against the
admitted snapshot: all 18 terminal outcomes, payoffs, message/call/reveal/token
counts, exact run IDs and seven strong-case agreement locators match. The
interrupted assignment has undefined terminal metrics, not imputed zeros.

The revised PDF is 11 pages: the main argument and references occupy pages
1--7, ethics/limitations is on page 8, and the complete record is on pages
9--11. `make -C report agentic` passed with no overfull boxes or undefined
references. All 11 pages were rendered and inspected, and a split-off total
row was repaired. All three quoted excerpts match the original R10.1 public
messages verbatim. Build log: `.harness/agentic-complete-results-build.log`.
The published `report.pdf` copy was refreshed after these checks.

Repository verification passed with `bash scripts/verify.sh`, including
Foundry/Rust checks, 294 legacy harness tests and 64 harness-v2 tests with
Docker/Anvil integration. The final Stop hook also returned `{}` after the
same gate passed. Logs: `.harness/verification-agentic-final-2026-10-26.log`
and `.harness/verification/run.PwP9Uv`. Raw archive CRC and JSON parse checks
passed independently; `git diff --check` reported no whitespace errors.

## Open gaps

- Human authors must review the semantic labels, source-to-claim links and
  final manuscript. The five authors are named; affiliations are pending.
- Official Apart template text was inspected, but this article layout has not
  been certified against its visual layout. Final required disclosures and
  submission formatting remain an author decision. No submission was attempted.
- No powered treatment estimate, representative collusion rate, model ranking
  or long-horizon generalization is supported. Larger independent blocks,
  domains, incentive variants and a calibrated positive honest baseline are
  further research.
- Early pilots may contain hidden SDK HTTP retries. Source snapshots preserve
  that distinction; the principal four trials use verified retry disabling.
  Stochastic model trajectories cannot be replayed bit for bit.
