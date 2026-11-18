# Control message delivery without changing discovery

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** harness, experimental observation controls

## Context

Removing messaging routes or changing participant instructions would make a
communication comparison also change discovery and the perceived task. A
pooling scenario with too few permitted inspections would additionally prevent
the compliant individual strategy it is meant to compare.

## Decision

Use `treatment.message_delivery = "normal"` or `"suppressed"` with identical
participant OpenAPI bytes, identity, system prompt, and mounted instructions.
The gateway forwards allowed sends and chat creation to Rust in both modes.
Suppression empties recipient forum/private message pages and chat listings,
including pagination metadata derived from upstream messages; the initial
scripted forum push is also empty. Rust retains the complete operator transcript
and normal communication audit. Gateway metadata records what was withheld and
what was returned without message bodies.

Build anonymous-jury labels from `Experiment.actor_ids`, including scripted
actors, rather than a fixed seven-seat list.

Allow a positive `scripted_peer_inspection_count` only for the records-inspection
peer and within `lookup_allowance`. It limits the scripted policy's inspections,
not evaluated accounts' allowance. An omitted count preserves the peer's full
historical allowance. A four-of-twelve peer can propose pooling while evaluated
jurors retain permission to inspect all twelve.

## Consequences

This isolates message delivery, not every possible communication mechanism.
Successful own-send receipts retain content, sequence and other metadata; chat
creation receipts, public actions, payments, timing, and enabled shared storage
remain possible carriers and must be reported. An upstream participant read in
Rust's audit does not prove content reached that participant: use gateway
delivery counts and the retained participant trace when assessing exposure.

Suppressing writes or deleting stored messages was rejected because attempted
coordination and operator evidence would be lost. Removing routes or adding a
notice was rejected because the participant interface would differ. These
mechanics and scripted tests establish neither spontaneous collusion nor an
empirical treatment effect.
