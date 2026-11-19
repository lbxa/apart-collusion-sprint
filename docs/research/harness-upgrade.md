# Collusion harness upgrade boundary

Date: 2026-11-17. This document describes the repository migration, not a model
experiment or a results admission. The accepted research anchor is Track 2.3,
standards of evidence for collusion; the first planned comparison is Track 2.2,
text-only, action-only, and combined detection.

## Shared execution, separate science

The current autonomous runtime developed in Epistemics replaces the older
structured-action harness and the separate `harness-v2` package. One active
`harness/` uv project owns `veracity_harness` and `game_api`. This consolidation
does not make the two research projects one benchmark.

The [runtime decision](../decisions/consolidate-the-collusion-harness-with-cloudflare.md)
and [research decision](../decisions/anchor-collusion-in-evidence-and-detector-comparison.md)
record the accepted boundaries. The [import manifest](../../harness/migration-source.json)
records selected pre-adaptation source-file hashes, source revision and dirty-tree
context, and the target base commit. It distinguishes imported source from final
Collusion changes; empirical runs still require their own complete provenance.

| Layer | Reused capability | Collusion-owned decision |
| --- | --- | --- |
| Game access | HTTP client, identity-bound gateway, authoritative receipts | Which coordination opportunities the mechanism permits |
| Model execution | Cloudflare adapter, tool loop, budgets, rate limiting | Model families, roles, prompts, call budgets, and assignments |
| Isolation | Private containers, network boundaries, safe diagnostics | Which channels and source material participants may see |
| Lifecycle | Episodic/continuous execution, memory, scripted setup | Relationships, financial continuity, exposure, and controls |
| Evidence | Traces, communication audits, commitments, settlement, hashes | Admission rules, independent references, semantic labels, and reviewers |
| Tracking | W&B inspection, upload, safe artifact selection | Separate credentials, project, campaign inventory, and release approval |
| Analysis | Deterministic extraction and scoring mechanisms | Estimands, denominators, uncertainty, comparisons, and paper claims |

Epistemics asks whether confidence and claim revision track evidence. Collusion
asks whether agents coordinate to compromise an obligation or process, what
actions implement that coordination, who benefits, and who is harmed. Shared
tasks can supply documents and reference checks. They cannot supply coordination
labels without an admitted opportunity, relevant observations, and review.

The game contract remains authoritative for financial rules. A provider adapter
cannot change payoffs; a detector cannot turn a jury verdict into ground truth;
an operator cannot fill missing participant actions to obtain a completed case.

## Compatibility and historical preservation

The imported runtime uses the matching modern HTTP SDK and ABI 2 game support,
including odd juries up to 15 and explicit withdrawal-credit transfers. An ABI
upgrade changes possible actions and incentives. Record it in prospective source
and configuration snapshots; do not present an ABI 1 historical case as having
these capabilities.

The exact root constitution is copied from the mature runtime for compatibility.
Its short form omits the evidence and independent-judgment duties present in the
fixed `principles` variant. New studies must choose and freeze delivered duties.
An obligation absent from an old run cannot be applied through later code.

The historical protocols, results, and example inputs from `harness-v2/` now
live together in [the October campaign archive](../../harness/archive/october-2026/).
The archive preserves the original evidence bytes and paths relative to the
campaign directory. The original harness guide is preserved as
`harness/LEGACY.md`. Source-only
collusion fixtures copied under `harness/research/` establish reusable inputs,
not new results, a standardized suite, or permission to rerun a campaign.

October discovery, later controlled recruitment, November swarm, and future
Collusion studies must retain distinct source registries and empirical claims.
Cross-study reuse requires provenance and a declared comparison. A larger pooled
count is not automatically a meaningful aggregate collusion statistic.

## Cloudflare and operator isolation

The default discovery example explicitly selects Cloudflare and requires an
explicit model ID. Frozen historical configurations retain their provider
interpretation. The adapter preserves conservative request reservations,
usage reconciliation, shared rate limits, malformed-history evidence, and safe
failure diagnostics. No availability probe in this migration generates text.

Cloud credentials are supplied by this repository's ignored `.env` or the cloud
worker secret environment. They are not copied from Epistemics or mounted in
participant containers. W&B uses a separately resolved Collusion destination:
`lbxa-corp/apart-collusion-sprint` on the standard API host. Tracking and artifact
storage do not supply compute; a worker must execute the harness independently.

The migration supplies no spending authorization. Before a live campaign,
recover existing state, select the worker, freeze assignments/configuration,
and retain one authorized ledger for all participating processes. Unknown
request costs retain reservations. Private recovery and spending databases
remain separate from ordinary published artifacts.

The campaign controller journals immutable assignments and verified private
inputs before dispatch. One controller lock protects recovery and ledger access;
restart continues pending assignments only and records stale running worlds as
interrupted without replay. Optional live W&B reporting exports safe progress.
Completed-run upload defaults to a numeric/provenance projection; private evidence
and raw model calls are separate explicit release choices. Deterministic scoped
upload IDs and durable intents keep retries tied to the same observation.

## Acceptance boundary

The [verification record](harness-upgrade-verification.json) retains the executed
checks, source/artifact hashes, historical-preservation checks, and zero-inference
and zero-remote-write accounting for this migration.

Repository acceptance requires the single-project setup and verification paths,
offline configuration/provider/accounting/scope regressions, and actual
Docker → HTTP → Rust → Solidity → Anvil integration checks. Model calls, funded
public wallets, and public RPC are excluded from default verification. Missing
Docker, listeners, or Foundry must be reported rather than silently skipped.

Passing those checks supports implementation claims only. It does not validate a
collusion detector or establish behavior across models, sectors, or conditions.
The [research contract](../benchmark.md) requires independently reviewed labels,
held-out groups, fixed detector comparisons, capability accounting, and a
design-appropriate uncertainty method before empirical claims are admitted.
