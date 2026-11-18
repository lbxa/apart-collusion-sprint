# Use SDK cache for periodic audit verification

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** Collusion periodic private archive verification

## Context

Whole-artifact network downloads became slower than the periodic archive cycle
as live trajectories accumulated. Requiring another network fetch for every
unchanged payload delayed verified partial evidence despite immutable versions.
The installed official W&B SDK supports artifact caching through
`Artifact.download(skip_cache=False)` and separately verifies files against the
artifact manifest.

## Decision

Provide the explicit watch-only `--use-sdk-cache-for-verification` flag. Reuse
the SDK's artifact cache rather than implementing a project cache. Each upload
still resolves its exact remote artifact version anew, compares its digest,
runs SDK manifest verification, and checks every payload's SHA256 against the
archive manifest. One-off uploads retain `skip_cache=True` by default.

Record `verification_download_mode=sdk_cache_enabled` in cache-enabled receipts,
along with the performed verification checks. Such a receipt does not claim
that every payload was newly downloaded over the network. Preserve prior
receipts and immutable artifact versions.

## Consequences

Unchanged content can be reused by the SDK, while uncached content still needs
retrieval. The existing failure boundary, completeness rules, secret checks,
and verified-payload pruning gate remain in force. An SDK or SHA256 verification
failure produces no verified receipt and cannot authorize pruning. SDK cache
storage remains separate from the owned snapshot payload cleanup.
