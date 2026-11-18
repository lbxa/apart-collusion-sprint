# Consolidate the Collusion harness with Cloudflare

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** harness, core, contracts, experiment operations

## Context

The separate Collusion checkout retains a structured-action harness and an
agentic `harness-v2`, while the Epistemics checkout contains the successor
runtime and subsequent collusion-specific operational fixes. Maintaining two
active harnesses obscures which execution and evidence paths are supported.
Lucas requested replacement with the mature runtime and Cloudflare support.

The common runtime does not make the experiments interchangeable. Epistemics
measures confidence, reference accuracy and revision. Collusion measures
coordination, applicable duties, implementing actions, benefits and harm.

## Decision

Maintain one active uv project in `harness/`, using the mature agentic runtime,
Cloudflare adapter, provider accounting, shared request limiter, trace watcher
and isolated W&B uploader. Remove obsolete executable harness code and build
paths. Retain historical evidence, original research inputs and spending ledgers
at their existing locations, including archival `harness-v2/results` paths.

Use the compatible ABI 2 contract, Rust API and Python client as one prospective
protocol version. Solidity remains the financial authority. Credit transfers
are exposed only by the configured treatment and remain separate from ordinary
settlement in retained evidence.

Collusion uses its own environment and W&B destination,
`lbxa-corp/apart-collusion-sprint`. Do not import Epistemics campaign drivers,
budgets, private keys, result registries or empirical labels. Runtime reuse does
not authorize model inference, historical uploads or new cloud campaigns.

## Consequences

- Historical ABI 1 and later ABI 2 cohorts remain separately identified; the
  upgrade does not revise old outcomes or participant obligations.
- Package installation and verification use `harness/uv.lock`; `harness-v2` is
  no longer an installable or executable package.
- The Cloudflare account and token are supplied through the Collusion runtime
  environment or runner secrets. The migration does not copy provider keys from
  another repository.
- Uncertain paid-request costs retain their reservations. Interrupted actions
  are evidence of unknown outcomes, not permission to replay them.
- A W&B uploader and live local trace viewer do not supply cloud compute or
  restart a financial world. Future campaign launch and recovery need an
  explicit runner and handoff.

Keeping both harnesses active was rejected because fixes and tests would drift.
Copying the entire Epistemics repository was rejected because its research
objectives, campaign authority and evidence cohorts are independent.
