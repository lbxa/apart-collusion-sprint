---
name: agentlens-tracing-instrument
description: Add Forge AgentLens tracing to Python or TypeScript agents. Use when asked to trace agent turns, model calls, tools, or subagents with Forge or AgentLens.
---

# Forge AgentLens instrumentation

Confirm the [trace destination and credentials](#check-the-trace-destination)
before editing an integration that exports to a backend.

Forge exports explicit agent spans through a private OTel provider. It does
not auto-instrument frameworks, replace the global provider, or export that
provider's spans.

After a valid login, read the [Python](references/python.md) or
[TypeScript](references/typescript.md) reference and
[trace fidelity](references/trace_fidelity.md) before editing.
Verify the APIs against the installed SDK version.

## Check the trace destination

Follow [AGENTS.md](../../../AGENTS.md) for credentials and artifact access.
The verified tracking scope is `lbxa-corp/apart-collusion-sprint` on
`https://api.wandb.ai`. Confirm AgentLens support and the actual trace endpoint
for the selected deployment independently. Historical Forge URLs confer no
credential scope. Verify access with a read-only identity or project query
through the configured SDK or connector. Use credentials in place and avoid
`login`, tracing `init`, and dummy runs as probes. Report unavailable network or
permissions as unverified access. For local validation, use synthetic traces
with a local OTLP receiver and report remote delivery as unverified.

For the harness, instrument operator-side boundaries under
`harness/src/veracity_harness/`. Keep runtime secrets outside participant
sandboxes. Suppress message, reasoning, and tool payload capture by default.
Use safe, explicit span fields and keep operator audit data on its existing
path. Any private trace export requires separate authorization.

## Instrument

- Confirm `entity/project`; a bare project cannot resolve its entity. Initialize
  once per process with runtime `WANDB_API_KEY`. Never print or commit credentials.
- Map Conversation → Turn → LLM/Tool/SubAgent to real boundaries: one turn per
  user exchange, one LLM span through stream consumption, one tool per execution.
  Preserve provider tool-call IDs and use explicit parents for delegated work.
- Preserve outputs, exceptions, retries, and cancellation. Close spans on failure;
  avoid duplicate capture from existing instrumentation.
- Keep project routing stable while work is active. Flush/shutdown at process
  exit, not per request. Python supports content suppression; this TypeScript
  revision requires omitting sensitive fields explicitly. Neither redacts PII.

## Implement incrementally

Add one traced path at a time: a model call, its tool loop, then delegation or
concurrency where applicable. After each change, run the path and follow
[read-back verification](references/read_back.md). Compare emitted and stored
spans with the actual execution before extending the instrumentation.

Fix mismatches and rerun the same check before continuing. Empty results,
failed queries, and unavailable checks are unverified, not passes. Stop at
that boundary and report what the user must do to unblock verification.

## Verify

Run the [conformance check](references/trace_fidelity.md#conformance-check)
for the paths you instrumented, including success, failure, and overlapping requests.
If the full suite requires CI, browsers, or unavailable services, run feasible
local checks and report the skipped coverage.
Assert parentage, tool-call IDs, and `gen_ai.operation.name` values
`invoke_agent`, `chat`, and `execute_tool` using Forge's provider or a local
OTLP receiver. Confirm backend arrival when authorized credentials are available;
otherwise report it unverified. Init/flush success alone is not delivery proof.
