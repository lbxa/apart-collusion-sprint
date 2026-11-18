# Separate startup recovery from confirmation evidence

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** Collusion campaign recovery and evidence admission

## Context

The US$300 continuation reached Docker image setup but failed before participant
startup or any model request. The five launchd property lists omitted `PATH`;
the default search path could not find `docker-credential-desktop` in
`/usr/local/bin`. All 75 previously pending cells retained terminal `StoreError`
records at `sandbox_image`, empty completed-episode lists and no model-call
files. The ledger remained at 11,426 requests. Local engine episode setup had
already begun, so these must not be described as never-started worlds.

With the frozen runtime's tools directory and Docker's executable directory in
an explicit launchd `PATH`, the existing actual Docker network, filesystem and
identity-isolation test passed. No model calls were used for this check.

## Decision

Retain the entire original 150-cell frame, all terminal failures, raw outputs,
journals, source hashes and budget holds. Do not reset a terminal journal row or
replay a failed world.

Collect separately identified recovery attempts for exactly the 75 cells selected
by the pre-restart pending-state backup and verified startup-failure audit. Keep
their tasks, configurations, model IDs, source order and seeds unchanged, and
link each new attempt to its original failed attempt. Selection depends only on
the recorded startup failure, with no model response available for those cells.

Mark the recovery register exploratory. Keep the original confirmation register
unchanged and do not pool recovery results automatically or count failed startups
as either collusion or resistance. Continue using the same US$300 spending
ledger, US$280 dispatch threshold and original UTC deadline. Verify the actual
background-job Docker environment before paid dispatch.

## Consequences

The recovery produces additional auditable attempts without erasing operational
attrition or changing participant instructions. The original confirmation study
retains its missing behavioral observations. Any later combined estimator needs
an explicit attempt-selection rule, lineage checks and a separately documented
analysis amendment; these infrastructure steps establish no behavioral result.
