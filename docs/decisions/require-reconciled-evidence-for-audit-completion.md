# Require reconciled evidence for audit completion

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** Collusion private audit archives and operator handoff

## Context

Independent review reproduced three gaps in the first private audit helper.
Aggregate progress counts could describe completion without matching retained
run evidence. The verifier checked file hashes without validating the canonical
content hash or unique manifest identities. The watcher returned success at its
deadline even when every upload failed.

The earlier receipts still identify immutable downloaded exports. Changing or
deleting them would obscure the actual validation performed at that time.

## Decision

Use `collusion-private-audit-v2` for subsequent snapshots. Validate its schema,
statuses, unique paths and run identities, and recompute its canonical content
hash. Reconcile assignment counts and rows with canonical job directories and
retained runs. A complete assignment needs exactly one matching complete run,
the configured number of episodes, matching terminal episode and summary
identities, and the required retained evidence. Missing failed or interrupted
attempts remain explicit gaps rather than disappearing from the archive.
Configured setup and transfer records, opportunity and gateway logs, and each
actor's trace and call files are required for complete execution evidence.
Missing or unsafe mandatory source files or directories force a partial archive.

Persist the latest observed content identity before attempting its upload. A
successful watcher boundary requires a verified v2 receipt for that content;
an older successful upload cannot satisfy the boundary for newer evidence.

Keep existing v1 receipts and their original source and export hashes. They
establish the downloaded file inventory and hashes that were checked, not v2
assignment completeness, metadata validation, or final watcher upload success.
Running frozen helpers are replaced through a separate operator action.

Allow explicit `--prune-verified-payloads` for long-running watchers because
repeated full local staging copies otherwise grow with both campaign size and
snapshot count. After fresh remote verification and a persisted matching v2
receipt, remove only that owned snapshot's payload copies. Retain its manifest
and receipt, every remote version, raw local evidence and frozen sources.
Unverified stages and recovery databases are outside this cleanup.

## Consequences

Incomplete or contradictory data can still be archived, with explicit gaps and
without a complete status. Strict verification can reject a snapshot while
concurrent writes are inconsistent; the bounded watcher observes later stable
bytes. Source snapshots, original evidence, prior receipts, private destination,
credential exclusions, inference authorization and spending limits remain
unchanged. Scientific scoring and interpretation require their own admission
review even when archive completeness is established.
