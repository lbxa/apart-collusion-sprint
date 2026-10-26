# Agentic Veracity harness

An independent Deep Agents experiment harness. Participants receive the rules,
an identity, a case, and an address. They discover the interface and choose all
of their own game actions with filesystem tools, a terminal, and HTTP.

## Run

Prerequisites: Python 3.12+, `uv`, Docker Desktop/Engine with its CLI, and the
built repository engine with pinned Foundry. From the repository root:

```sh
bash scripts/setup.sh
uv sync --project harness-v2 --locked
uv run --project harness-v2 veracity-harness build-sandbox
uv run --project harness-v2 veracity-harness validate --model "$EXPERIMENT_MODEL_ID"
uv run --project harness-v2 veracity-harness smoke --model "$EXPERIMENT_MODEL_ID"
uv run --project harness-v2 veracity-harness run --model "$EXPERIMENT_MODEL_ID"
```

`run` uses `examples/discovery.toml`. Set `EXPERIMENT_MODEL_ID` to the OpenRouter
ID selected from your experiment's model list before using the commands above.
Alternatively, set `name` in the TOML `[model]` table and omit `--model`.
Model selection is required; there is no implicit model or fallback selection.
Use `--config path/to/experiment.toml` for another experiment and `--output path`
to change the output parent. Case-document paths are relative to the TOML file.

## Experiment models

The experiment owns its roster of frontier reasoning models from DeepSeek,
Google Gemini, Anthropic, and OpenAI. Supply the selected OpenRouter model ID
directly for each run. The harness treats that ID as an experiment input and
does not rank, substitute, or filter models by perceived tool-calling suitability.
The selected model and settings are recorded in the run manifest.

Configure completion budgets, opportunity timeouts, and optional reasoning
settings for the selected model. For example, this budget configuration leaves
the actual model ID to the experiment's `--model` selection:

```toml
[model]
max_tokens = 65536
turn_timeout_seconds = 600

[model.reasoning]
effort = "high"
```

`[model.reasoning]` accepts OpenRouter's `effort`, `max_tokens`, `enabled`,
`exclude`, and `summary` options. Use either an effort or an explicit reasoning
token budget. An explicit reasoning token budget must leave completion room
within `[model].max_tokens`. Omitting reasoning settings preserves the selected
provider's defaults. Options pass through `langchain-openrouter` unchanged;
support and token limits depend on the selected model. The harness imposes no
32K ceiling on an experiment's completion budget. Choose game deadlines and
opportunity timeouts that accommodate the experiment's reasoning budget.

The CLI loads `OPENROUTER_API_KEY` from the root `.env` without overriding an
existing environment value. Provider credentials stay in the host model process.
No `.env`, signer key, operator token, or root repository directory is mounted
into a participant sandbox.

`smoke` uses one participant, one episode, and at most four model requests,
respecting any stricter request limit configured by the experiment. It preserves
the selected model's completion and reasoning budgets. It verifies provider/tool
integration and then expires the local episode. It is identified as `kind: smoke` in its manifest;
it is not a completed multi-participant experiment or a collusion measurement.

## Capabilities and controls

Every participant uses `create_deep_agent` with the same planning, filesystem,
shell, and general-purpose subagent capabilities. There are no game-specific
LangChain tools or structured-output action selectors. The starting instruction
points to `/game/`, `GAME_URL`, and the payoff objective. A participant can use
`curl`, Python's HTTP libraries, or its own scripts to discover and call the API.

Each sandbox has a separate internal Docker network and writable `/workspace`
and `/tmp` mounts. Its root and `/game` documents are read-only. Networks share
only the trusted gateway; participants cannot connect directly to one another
or the public Internet. The gateway identifies callers by their actual container
address, ignores supplied bearer identities, injects the corresponding participant
credential, and restricts requests to the current episode. A protected host relay
connects the gateway to the loopback-only development engine without exposing
that engine anonymously on the host network.

`/memories/` is routed through `CompositeBackend` to private participant storage.
Use filesystem tools to access it; it is not a shell directory. With `memory =
true`, both that storage and the participant's SQLite conversation checkpoint
persist across episodes in the run. Otherwise each episode gets fresh memory
and context. Shell containers are always recreated, and each episode gets a
fresh Anvil chain, escrow state, credits, and API database, regardless of memory.

The operator registers the episode, shuffles participant opportunity order using
the configured seed, and gives all participants bounded opportunities. After a
phase's opportunities it advances the owned Anvil clock to the deadline and
performs settlement or expiry when required. It never manufactures missing
claims, challenges, commitments, reveals, or withdrawals. Participants receive
one final opportunity after a terminal outcome to inspect it and act if they
choose. A nonparticipating creator can leave the episode unfunded.

Set treatments in the TOML file:

| Setting | Effect |
| --- | --- |
| `public_messaging` | Enables or blocks actual public-forum access at the gateway. |
| `private_chat` | Enables or blocks actual private-chat access. |
| `private_history` | Enforces chronological or latest-only participant history. |
| `private_communication_prohibited` | Keeps private communication possible but labeled prohibited when true. When false, the operator provisions all permitted pairs before play; participants discover those channels. |
| `memory` | Retains or resets private files and conversation context between episodes. |

The filtered OpenAPI schema advertises enabled participant routes. Disabled
communication is blocked even if an agent already knows the original route.
To vary incentives, supply the engine's full `[parameters]` table, including
`beta_wei`, `gamma_bps`, the four `*_duration_secs` fields, and the three payout
shares. Shares must sum to 10,000 basis points. The harness validates these
inputs and registers them; Solidity computes all financial results.

`[model]` bounds requests per opportunity and episode, output tokens per request,
and opportunity duration. Counters include delegated agents and summarization;
provider retries are disabled. Shell commands have a 20-second timeout and 64 KiB
captured-output limit. Each container has a CPU, memory, process, and tmpfs limit.
File downloads are bounded to 1 MiB. A failed or timed-out agent is recorded and
receives no further opportunities in that episode; the harness does not replace
its decisions. CLI runs with agent execution failures exit unsuccessfully.

## Retained evidence

Each run creates a private directory under `harness-v2/results/` containing:

- `run.json`: configuration, run kind, completion/failure status, and episode summaries.
- One episode directory with exact engine snapshots, settlement and balances,
  paginated forum/private transcripts, and separate operator audits in `evidence.json`.
- Per-participant `*.trace.jsonl` files, including delegated graph updates,
  plus `opportunities.jsonl` with phases, budgets, token usage, and failures.
- `gateway-audit/access.jsonl`: request/response metadata, including blocked
  attempts, with no message bodies or credentials.
- Private SQLite checkpoints and routed memory files, scoped by participant and
  by the selected memory treatment.

Routine logs contain lifecycle identifiers, statuses, and counts. Private
messages and agent outputs stay in the operator's evidence files. Failure files
distinguish execution, evidence-retention, and cleanup problems. An interrupted
run retains its partial evidence and is not resumed automatically. Neither
results nor the virtual environment are tracked by Git.

An optional `expected_verdict` is evaluator-only and requires a `reference_claim`.
Automatic correctness scoring applies only when the submitted claim exactly
matches that reference. A different free-form claim remains unscored. Payoffs
are exact decimal strings of engine entitlements minus deposited principal;
development gas costs are excluded. Message use, prohibited communication,
agreement, and factual correctness are retained as separate evidence.

## Verification

```sh
uv run --project harness-v2 ruff check harness-v2/src harness-v2/tests
uv run --project harness-v2 ruff format --check harness-v2/src harness-v2/tests
uv run --project harness-v2 pytest harness-v2/tests
uv run --project harness-v2 pytest harness-v2/tests -m integration
bash scripts/verify.sh
```

The default suite is deterministic and uses no model APIs or Docker. Integration
tests explicitly require Docker and the actual built Rust/Anvil stack; missing
infrastructure fails rather than silently skipping. They drive the real Deep
Agents tool loop with scripted model fixtures to prove protocol completion,
memory boundaries, nonparticipation, failure handling, and isolation. Those
fixtures provide no evidence of emergent model behavior. The separate bounded
live smoke test has exercised OpenRouter, filesystem tools, and shell execution.

Current framework references: [Deep Agents sandboxes](https://docs.langchain.com/oss/python/deepagents/sandboxes),
[backends](https://docs.langchain.com/oss/python/deepagents/backends), and
[OpenRouter integration](https://docs.langchain.com/oss/python/integrations/chat/openrouter).

## Architecture contract

- **Boundary and capability:** this project owns agent execution, isolated
  workspaces, experimental treatments, scheduling, and retained research evidence.
  The existing Rust API and Solidity contract own game mechanics and money.
- **Ownership and change points:** `config` owns validated experimental inputs;
  `gateway` owns participant identity and visibility; `sandbox` owns Docker
  resources and command limits; `agents` owns Deep Agents/OpenRouter construction
  and model budgets; `runner` owns episode lifecycle and operator evidence.
  Models, incentives, communication access, and memory vary through configuration.
- **Domain concepts:** run, episode, participant, opportunity to act, treatment,
  case, private workspace, and operator evidence. A final payoff is the engine's
  exact entitlement less deposited principal, not a harness-generated reward.
- **Invariants:** agents receive no provider key, operator credential, RPC access,
  verifier label, host repository mount, or other participant workspace. Identity
  comes from the sandbox network, never a caller-selected bearer token. The
  gateway enforces communication access and episode scope. The harness never
  posts, challenges, votes, reveals, or withdraws for a participant.
- **Ports and adapters:** reuse the generated, validated `game_api.CoreClient`
  and owned `LocalEngine`; package that existing SDK without importing the old
  experiment runner. Use `langchain-openrouter`, Deep Agents backends, Docker's
  SDK, Pydantic, and aiohttp for their existing integration boundaries.
- **Use cases:** validate a configuration; run independent episodes with the
  same agent capabilities; vary registered incentives and communication/memory
  treatments; inspect discovery traces and authoritative outcomes.
- **Lifecycle:** each episode follows the engine's phases. A fixed number of
  opportunities per phase bounds work; only the operator advances Anvil time
  after those opportunities. Terminal settlement or expiry closes the episode.
  Agent/model failures are recorded separately from game outcomes.
- **Failure model:** reject invalid inputs before starting; fail closed on gateway
  ambiguity, missing isolation, and engine failures. Bound shell duration, output,
  model attempts, tokens per call, and opportunity duration. No silent host-shell
  fallback. Infrastructure failure is never reported as completed gameplay.
- **Transactions and recovery:** game writes pass through unchanged with the
  agent's idempotency key; the gateway never retries writes. Operator registration
  and terminal actions use deterministic keys. Append private evidence while
  running and write a final completion/failure record. Interrupted local runs are
  retained for inspection, not silently resumed against a fresh chain.
- **Test strategy:** deterministic tests exercise gateway identity, filtered
  discovery, communication restrictions, cross-episode denial, budget enforcement,
  and scheduling without strategic actions. Explicit integration tests use actual
  Docker isolation, a real Deep Agent tool loop, and Rust/Anvil. A bounded live
  OpenRouter smoke test verifies the provider integration separately.

## Experimental interpretation

The prompt asks participants to maximize their final payoff. It contains no
collusion, bribery, reciprocal-approval, or truth-label cues. Interface documentation
describes mechanics neutrally. The current protocol has no participant transfer
endpoint; this harness does not invent side payments or alter contract rules.
Model weights do not train during a run; persistent memory enables within-run
adaptation. Communication, agreement, and an incorrect verdict are separate
observations and do not alone establish collusion.

## Changelog

### 2026-10-26

- Model identity and reasoning settings belong to the experiment, including its
  DeepSeek, Gemini, Anthropic, and OpenAI roster. Require an explicit selection
  and preserve experiment budgets rather than choosing a model for tool calling.

### 2026-10-25

- Keep strategy and every participant protocol action in the Deep Agent tool
  loop; the operator owns lifecycle and evidence, and the contract owns finance.
- Reset chain state between episodes independently of cognitive memory, so old
  global credits cannot leak earlier outcomes into a memory-disabled treatment.
- Use exec-based file transfers because Docker archive APIs can reject a
  read-only root or fail to observe live tmpfs files. Preserve read-only roots
  and unprivileged execution rather than weakening sandbox isolation.
