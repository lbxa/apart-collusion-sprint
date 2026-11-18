# Archive authorized Collusion trajectories in private W&B

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** Collusion campaign evidence and tracking

## Context

The campaign's live observer exports progress and numeric provenance. Those
records cannot reconstruct what participants were shown, said or did. Lucas
explicitly authorized retaining benchmark text and experimental outputs in the
private Collusion W&B project after the initial launch was blocked for unclear
destination authorization.

## Decision

Archive the authorized campaign's benchmark inputs, delivered prompts, model
responses, tool actions, outcome evidence and frozen source inventory in
versioned artifacts under `lbxa-corp/apart-collusion-sprint`, using the supplied
key only with `https://api.wandb.ai`. Include failed and partial attempts.
Verify downloaded artifacts against file hashes before treating an archive as
complete. Keep original local files unchanged; exported redactions have separate
hashes and a manifest linking them to the originals.

Provider/operator credentials, wallet keys, recovery databases and spending
ledgers remain outside these evidence artifacts. This authorization does not
permit public release. Inference remains on Cloudflare, CPU work remains local,
and the shared API ceiling remains US$100.

## Consequences

The numeric-only default remains useful for ordinary telemetry, but this study
explicitly opts into private evidence and raw model calls. An upload attempt or
live tracking link is not proof that all evidence has been archived. A verified
receipt records the immutable artifact version and hashes. Scientific labels
remain separate from stored trajectories and require their own review.
