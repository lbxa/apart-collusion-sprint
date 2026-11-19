# Collusion Sprint skills

This directory is the repository's skill source; `.claude/skills` points here.
Copied skills supply instructions and helper files, not credentials, installed
dependencies, compute, or permission to spend or publish.

## Package ownership

- `contracts/` owns financial rules; `core/` owns the Rust `/v1` API and recovery.
- `harness/` is the sole active Python project. Its `src/game_api/` owns the HTTP
  SDK and local engine launcher; `src/veracity_harness/` owns agents, gateways,
  controls, evidence, and scoring. Use its manifest and `uv.lock`.
- `harness/archive/october-2026/` holds the October campaign records. Preserve
  the recorded source, evidence, and duties for historical interpretation.
- `docs/benchmark.md` owns Collusion's measurement contract. Reused Epistemics
  execution code does not transfer hypotheses, labels, budgets, or findings.
- `report/` has its own reporting guide, paper brief, venue rules, and review
  process. Use [editor](editor/SKILL.md) alongside `docs/reporting/README.md`.
- `website/` owns the Astro research site. Use [shadcn](shadcn/SKILL.md) for its
  components and run the website checks from that directory with Bun.

## Routing

Use `code-craftsmanship` and `anti-slop-code-architecture` before non-trivial
runtime changes. Use `tdd`, `quality-assurance`, and `verify` for the relevant
Rust/contract behavior and full verification. Framework skills explain the
existing implementation; do not scaffold another harness from quickstarts.
Use Context7 for current dependency or tool APIs.

Use `wandb-primary` for read-only inspection, runs, metrics, and artifact work.
New work targets `lbxa-corp/apart-collusion-sprint` on the standard W&B API host;
follow `AGENTS.md` for credential handling, cloud execution, and separation from
Epistemics. W&B is not a compute runner. Uploading private traces or starting
paid inference requires authorization beyond possessing a key.

- [agentlens-tracing-instrument](agentlens-tracing-instrument/SKILL.md) handles
  requested Forge instrumentation after verifying the trace endpoint and scope.
- [wandb-autoresearch](wandb-autoresearch/SKILL.md) handles authorized Launch
  training jobs. Collusion benchmark runs follow the campaign workflow in `AGENTS.md`.
- [wandb-eval-tables](wandb-eval-tables/SKILL.md) handles bounded previews of
  existing W&B Tables. Use authorized numeric or provenance projections by default.

Use `capture-tacit-knowledge` for durable package decisions and `entropy-reducer`
to inspect the touched diff before handoff. Preserve concurrent edits, existing
ledger holds, historical source hashes, and the full operator audit transcript.
