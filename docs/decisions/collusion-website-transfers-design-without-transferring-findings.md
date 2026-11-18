# Collusion website transfers design without transferring findings

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** website, research communication

## Context

Lucas requested a Collusion Sprint research companion following the approved
Epistemics site's design, with all website code in the top-level `website/`
folder. The Collusion report is still developing. Its current confirmation
snapshot contains no admitted estimates; October case studies are separate.

## Decision and architecture contract

`website/` owns a self-contained static Bun/Astro site, its source-pinned numeric
export and copied paper snapshots. It reuses the ruled header, light palette,
shadcn controls and restrained motion. It imports no Epistemics findings.

The export adapter validates pinned report inputs with Zod, projects only safe
aggregate fields and preserves null scores. Pending confirmation slots never
receive fabricated points or intervals. Historical counts retain their date,
review status and separate denominator. Model families, input hashes and paper
revisions can change through explicit source-manifest updates after review.

Astro owns chart and prose rendering; a small React select island owns filtering.
There is no backend, model call, spending ledger, or automatic publication. The
filesystem adapter checks source hashes before producing deterministic exports;
mismatch or invalid counts fail the build. Re-running synchronization is
idempotent. No database transaction or additional status workflow is needed.

Tests cover missing estimates, private-field exclusion, historical count
reconciliation, source mismatch and static fallbacks. Browser review covers
mobile layout, filters and reduced motion. Research and experiment files remain
owned by their existing packages.

## Consequences

The site can develop before new collection is admitted. New results require a
reviewed source revision and updated manifest, not a change to copied example
numbers. Paper links identify the working and historical manuscripts separately;
no film, deployment domain, affiliation or new finding is invented.
