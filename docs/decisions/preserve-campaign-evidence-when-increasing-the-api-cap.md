# Preserve campaign evidence when increasing the API cap

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** Collusion campaign operation and recovery

## Context

Lucas increased the existing Collusion campaign's total API spending limit from
US$100 to US$300. This is a total limit, not an additional US$300. The spending
ledger retains charges and unresolved request holds. The frozen controller also
includes the cap in its campaign fingerprint, so changing the ledger alone
cannot resume an existing journal.

The original `launchctl submit` registrations also restarted controllers after
exit code 1. Existing failed assignments caused that code even when the latest
controller stopped without dispatching at the US$80 threshold. Those repeated
controller starts are operational events, not additional experimental trials.

## Decision

Amend the original ledger through its explicit cap-increase operation. Keep every
request row and unresolved hold. Use a US$280 threshold for starting assignments,
leaving headroom under the shared US$300 hard cap.

Permit a journal identity amendment only after checking that the source, inputs,
configuration, assignment fingerprints, order and statuses are unchanged and no
assignment is running. Back up the journal and mutable projections first. Retain
the previous frozen record and the old-to-new campaign identity link in an audit
record. Preserve earlier remote runs; the amended identity gets its own tracking
record. Resume pending assignments only.

Use explicit one-shot launchd property lists with `KeepAlive=false` and
`RunAtLoad=true`. Bind the independent UTC deadline guard to newly verified
controller identities. A cap increase does not extend the execution deadline.

## Consequences

The same experimental assignments continue under a documented financial
amendment. Failed or interrupted worlds are never replaced to improve apparent
completion, and unknown billing remains conservatively reserved. Earlier
campaign fingerprints and remote controller runs remain valid historical
provenance and must not be counted as new observations.

The model runtime and delivered participant material remain frozen. Cap and
controller changes are operator infrastructure changes; they supply no evidence
about collusion or model resistance.
