# Run authorized CPU work locally with Cloudflare inference

- **Date:** 2026-11-17
- **Status:** Accepted
- **Deciders:** Lucas Barbosa
- **Area:** experiment execution, operator credentials, spending

## Context

The reachable configured cloud worker lacks Docker and its daemon socket, while
the other inspected aliases were unreachable. The current agent harness needs
its tested Docker isolation. After this was reported, Lucas instructed: "For any
compute that is CPU-bound, run it on my local computer."

Lucas separately authorized a fresh US$100 model API ceiling for this study.
Earlier Epistemics and Collusion campaign ledgers remain separate.

## Decision

Run Docker, Anvil, campaign orchestration, tests, analysis and report compilation
locally. Native Cloudflare Workers AI remains the inference provider. This is
the user's explicit execution exception to the repository's cloud-worker default.

Use one new immutable US$100 spending ledger, including unresolved request
reservations. Stop dispatching pilot assignments at a cumulative US$10 accounting
threshold and confirmation assignments at US$80, leaving review and safety
headroom. These thresholds stop new assignments; a current assignment may
finish above the threshold while the hard ledger cap still applies.

Run the campaign from a frozen source snapshot under OS-managed detached
execution with a bounded deadline. App restarts must not resample started jobs.
Operator credential loading selects Cloudflare values from the already supplied
provider environment and the separate Collusion tracking key and destination.
Credentials do not enter arguments, participant workspaces, report sources or
ordinary artifacts.

## Consequences

- The execution location is local; inference requests and safe live tracking
  still reach their explicitly selected services.
- Preserve source hashes, complete assignment states, conservative spending,
  private recovery data and safe progress so a fresh app session can inspect it.
- Source changes require a new frozen runtime identity; report and analysis
  edits cannot mutate a running participant environment.
- A deadline interruption preserves unknown costs and interrupted worlds.
  Only unstarted assignments may continue under the same authorization.
- This exception does not authorize a paid VM, a budget increase, a model
  substitution, or public release of private trajectories.
