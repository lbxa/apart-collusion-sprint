# Enforce the local campaign deadline with rechecked UTC

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa, through delegated campaign authority
- **Area:** Local campaign lifecycle and spending authority

## Context

The laptop's observed clamshell sleep advanced wall time by about 24 minutes
while recorded active-time intervals advanced far less. A relative process
wait computed once at launch therefore cannot by itself establish the promised
absolute UTC deadline. Existing launchd children also ignored SIGINT during the
audit-watcher upgrade. The campaign remains authorized only within its recorded
deadline and shared API cap.

## Decision

Run a separate, local guard against the five captured controller identities.
Recheck UTC at intervals no longer than one second. At the recorded deadline,
revalidate PID, process group, process start identity, module and exact output
directory before sending SIGTERM. After five seconds, send SIGKILL only if the
same original identity remains. Exit when captured controllers have ended.

Keep the guard separate from frozen experimental code. It starts no model
requests and never edits journals, releases spending holds or replays work.
Retain unfinished attempts as deadline-limited evidence. Record signals actually
sent rather than claiming graceful finalization.

## Consequences

The UTC boundary remains enforceable after host sleep without changing model
conditions or the budget. Identity changes prevent signaling and are explicit
in the guard receipt. The guard does not prevent clamshell sleep or recover
provider responses lost during a disconnected interval; local operators must
keep the lid open and preserve uncertain charges.
