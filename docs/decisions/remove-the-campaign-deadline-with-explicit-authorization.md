# Remove the campaign deadline with explicit authorization

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** Collusion campaign operation and private evidence monitoring

## Context

Lucas explicitly instructed: "No time requirement at all. Go for as long as
needed." The campaign's US$300 total API cap remains unchanged. Earlier launch
and archive records retain the former 00:32:27 UTC deadline as historical
provenance.

That deadline stopped five active recovery controllers. Four sessions had
completed, five were active when stopped, and 66 remained pending. A stale
`running` projection does not establish that its controller is still alive.

## Decision

Use an explicit `--no-deadline` mode for the campaign launcher and private audit
watcher. Record a null deadline and the selected time policy; do not substitute
a distant date or repeatedly extend a hidden timer. Bounded launches still
require their explicit deadline, and the two modes are mutually exclusive.

Back up stopped journals and mutable projections before resuming. Retire the
expired controller/guard registrations. Resume the same frozen plans and
campaign identities through native journal recovery, which marks stale active
assignments interrupted and dispatches pending assignments only. Preserve the
five interrupted attempts and their unknown request holds.

Keep the original spending ledger, US$300 hard cap and US$280 threshold for
starting assignments. Retain the frozen model runtime, participant material,
seeds and game/request timeouts. The removed limit is the overall campaign
execution window.

The private watcher uses a new stage and explicit unlimited-time binding.
It observes every declared controller until stopped, retains pending and
incomplete evidence, and verifies the final observed content before success.
It must not turn a budget stop into completed assignments.

## Consequences

The finite assigned queues may finish without a wall-clock cutoff while cost
and evidence authority remain intact. Earlier deadline interruptions remain
research attrition, not resistance or successful completion. No interrupted
world is replayed, no ledger is replaced, and no results are pooled implicitly.
