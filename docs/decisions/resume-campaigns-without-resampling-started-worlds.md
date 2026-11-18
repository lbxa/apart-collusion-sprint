# Resume campaigns without resampling started worlds

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** harness campaign lifecycle, tracking, spending

## Context

A per-run directory and model checkpoint do not establish which campaign
assignments remain unstarted. Restarting an ordinary loop can create new run
identities and repeat paid requests or financial worlds whose outcomes are
unknown. The accepted harness upgrade includes durable assignment accounting
and recovery. W&B availability must not decide whether an assignment executes.

## Decision

Freeze assignment identities, effective configurations, source/input hashes and
the shared spending ledger before dispatch. Use an exclusive campaign controller
and an authoritative SQLite journal. Only pending assignments can start; a
running assignment interrupted by controller loss becomes interrupted and is
never automatically replayed. Completed and failed observations are immutable.

Retain atomic local progress and assignment-bound run directories. Live W&B
tracking is an optional observer with stable identity; degraded telemetry cannot
replace or reset authoritative assignment states. Finished-session upload uses
a persisted intent and deterministic remote identity so retrying does not
silently create a new experimental run.

## Consequences

- Campaign resumption continues unstarted work. It does not reconstruct a lost
  chain, replay an uncertain action, reconcile an unknown API charge, or replace
  a failed assignment.
- A scientifically justified replacement is a new identified assignment with
  its own declared inputs and authorization, retaining the original attempt.
- One shared spending ledger retains all confirmed charges and unresolved
  reservations. Changing the plan, inputs, source or cap requires an explicit
  new campaign identity rather than modifying frozen observations.
- Ordinary remote exports contain safe metrics and provenance. Private evidence
  and model-call content require explicit inclusion; credential and database
  exclusions still apply. Operator journals and upload-intent files remain local.
- This implementation and its scripted tests authorize no new model calls or
  campaign uploads.
