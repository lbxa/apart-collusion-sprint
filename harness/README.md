# Collusion Experiment Harness

Python agents, treatments, deliberation, and metrics for the Veracity game.
Normal experiment commands wrap the Rust engine through its `/v1` HTTP API.
Solidity remains authoritative for deposits, deadlines, votes, and settlement.

## Setup and local execution

From the repository root, install Rust and uv, then run:

```sh
bash scripts/setup.sh
cargo build --workspace --locked
harness/.venv/bin/python harness/run_knockout.py \
  --condition knockout_honest --dry-run --episodes 2 \
  --output .harness/experiments/honest
```

This needs no model credentials or public RPC. `--dry-run` / `--scripted`
selects scripted agents while preserving actual Rust, SQLite, Solidity, and
Anvil execution. The adapter starts a fresh server and local chain, discovers
their exact loopback ports from startup JSON, and shuts down both afterward.
Do not start a second server manually for these commands.

Use `--list` to inspect conditions. `--pilot`, `--minimum`, and `--full` select
knockout suites. `run_experiments.py` provides the original treatment catalog
and comparisons, and `--cell` runs one cell of the factorial design in
[`docs/experiment-design.md`](../docs/experiment-design.md), by cell ID or named
condition (`--cell K2`). `smoke_llm.py --cell F` is a one-round live-model check. Both entrypoints default to the real engine; `--mock` explicitly
selects a harness-only simulation. `run_demo.py` is a mock-only illustration.
`--core-engine-dir` or `CORE_ENGINE_DIR` optionally selects another built checkout.

To use model agents, omit `--dry-run` and supply the provider credentials through
environment variables. Never commit them. Runs with infrastructure failures
save diagnostic records and exit unsuccessfully; failures do not become verdicts.

## Weights & Biases

`run_experiments.py --wandb` creates one online W&B run per treatment block.
All blocks in one invocation share a unique group; `--wandb-group` can supply
a deliberate group name. Cell runs record the total block count and one-based
block index; treatment comparisons leave both fields null because their runs
are distinct conditions. `--wandb-project` and `--wandb-entity` override
`WANDB_PROJECT` and `WANDB_ENTITY`; otherwise the project is `apart-collusion-sprint`
under the account's default entity. Set project privacy in W&B before running.
The harness preserves the project's existing access settings.

The CLI loads the repository `.env` with `python-dotenv`, preserving values
already in the process environment. `--env-file` selects another file.
Put `OPENROUTER_API_KEY` and `WANDB_API_KEY` there and keep it untracked.
For the first jury plumbing check, keep all six factors off and use two clear
scenarios (one true, one false):

```sh
harness/.venv/bin/python harness/run_experiments.py \
  --cell M0-C0-T0-R0-S0-E0 --blocks 1 --episodes 2 \
  --wandb --wandb-project apart-collusion-sprint --run-purpose smoke \
  --output .harness/experiments/jury-baseline-smoke
```

This preserves seven jurors and three public deliberation rounds. It uses live
models and the real Rust/Anvil engine. The short run verifies integration;
the design's first pass uses two fresh blocks of ten episodes each. The explicit
all-off cell differs from the older named condition `A`, which retains majority
pay (`M1`). Use the full cell ID for this baseline.

`--model PROVIDER/MODEL` explicitly selects the same model for the creator,
challenger, and all LLM jurors, including juror overrides. Providers and treatment
factors stay unchanged; omitting it preserves the configured model defaults.
`--lineup NAME [NAME ...]` (with `--cell`) runs each block once per named model
lineup from `experiments/design.py`: the creator and challenger may use different
models, and every juror and auditor shares the jury model. `--list` prints the
lineups, and the [Models factor](../docs/experiment-design.md#models-l-categorical)
defines them. `--model` and `--lineup` are mutually exclusive.
`run_lineups.py CELL... [--lineup NAME ...] [--jobs N] [-- OPTIONS]` runs each cell
once per lineup in parallel, one process and log per pair, in one W&B group.
Use a fresh output directory and W&B group when retrying with another model,
and keep quota failures visible as failed runs. W&B records the selected model
for each role so runs using different models can be compared separately.

W&B receives an allowlist of scientific configuration, code revision and dirty
flag, scenario order, model settings, protocol rates, per-episode jury metrics,
weighted block summaries, and an episode table. `jury/*` contains episode
measurements; `block/*` contains pooled counts and rates with their denominators.
Undefined rates remain null. With private channels disabled, message counts
are zero and abuse rates are unavailable. Cross-episode consistency under
`R0` is descriptive because agents have no memory. Agreement alone does not
establish collusion; see the [measurement definitions and permutation
procedure](../docs/experiment-design.md), including the evidence-set confound.

Credentials, prompts, message bodies, transcripts, agent reasoning, monitor
evidence, private observations, raw failure payloads, source code, git diffs,
console capture, and system metadata are excluded from W&B runs. Detailed
evidence stays in local experiment exports. Each episode's `llm_calls` there
holds one entry per model call: the parsed reply without its `reasoning`, the
model's hidden reasoning when it returns any, the `reasoning` the agent wrote in
its JSON reply, and the OpenRouter provider that served it. Agents never see each
other's reasoning. The SDK's working files live below the selected output
directory, and `wandb_runs.jsonl` records the dashboard links before model
execution. Initialization or upload errors fail the command; recorded
infrastructure failures mark the W&B run failed. Omitting `--wandb` makes no W&B
calls.

## Weave tracing and the chain-of-thought monitor

`--weave` traces every model call to W&B Weave in the same project: the full
prompt (including private chat the agent can see), the reply, and the model's
hidden reasoning, labelled with `episode_id`, `agent_id`, `role`, `phase` and
`round`. Unlike W&B runs, Weave traces therefore hold raw experiment content;
the team chose this on 2026-10-25 to inspect reasoning. Omitting `--weave` sends
nothing to Weave.

`--cot-monitor [MODEL]` asks whether each agent went rogue. After every completed
episode a separate model (default `anthropic/claude-haiku-5.5`) judges each LLM
agent twice, from its actions alone and from its actions with its reasoning, and
combines the two as in the CoT Red-Handed hybrid monitor. Judgements, with an
evidence quote, are saved in the episode's local `cot_monitor`; `cot_*` counts
and rates reach W&B with the other jury measurements. With `--weave`, each
judgement is a `cot_monitor` trace. A failed judgement is counted and never fails
the episode. See the [measurement definition](../docs/experiment-design.md).

OpenRouter requests sort providers by throughput (`provider.sort`); each call
records the provider that served it.

## Protocol and units

- Supported real juries have 3, 5, or 7 distinct members. Rules and rosters freeze
  at registration. Larger mock juries are simulations of a different protocol.
- One harness token maps to **100 integer native base units**. Historical `$`
  labels in prompts describe simulated utility, not fiat or valuable currency.
  Decimal conversion rejects fractional base units and inexact basis points.
  Equal party stakes, juror bond, and all payout shares come from the treatment.
- The explicit mock preserves the earlier harness simulation, including
  independent juror bonds, larger juries, and floating payouts. Its metrics
  describe a different protocol and must not be pooled with real engine results.
- Juror deposits occur with confirmed commitments. A juror who never commits
  deposits nothing. A committed juror who withholds a reveal forfeits the bond.
  Treatments can set `withhold_reveal_indices` explicitly to test the latter.
- The adapter advances only its owned local Anvil to absolute contract deadlines.
  Run episodes sequentially on that node; use separate adapters for concurrent
  local runs. This convenience mode does not attach to public deployments.
- Actual claim text, counter-evidence, and final assessments reach the engine.
  Enabled public deliberation is posted to and read from the core's episode
  forum. Round scheduling, straw polls, and simulated bribes stay here.
  The runner enforces configured channels and keeps ground truth in evaluation.
  Scripted honest baselines receive explicit oracle labels as test doubles;
  their accuracy is plumbing evidence, not evidence about model ability.
- Settlement and per-episode balances come from the engine. No cached vote or
  mock calculation can substitute for a failed or unconfirmed chain operation.

See [the API guide](../docs/api.md) and [integration contract](../docs/integration.md).
`GAME_API_CONTRACT.md` and `GAME_BUILDER_HANDOFF.md` are historical proposals.

## Structure and results

`game_api/client.py` provides `CoreClient` for existing deployments, configured
with an HTTP(S) URL and role credentials. Its `commit`, `reveal`, and `settle`
methods each submit one protocol action and return an operation handle;
`wait_operation` verifies a successful confirmed receipt. It owns no processes
or clock. See the [Python client guide](../docs/api.md#python-client).

The client also supports [private chat](../docs/private-chat.md): participants
can create/list their chats and send/read messages; operators can provision
controls, inspect retained transcripts, and read usage audits. These methods
return typed chat data directly. The experiment runner exposes private messaging
when `private_chat=True`, with participant-specific history and separate usage
audits. Its public-channel configuration controls the core forum independently.

The [public forum](../docs/public-forum.md) is engine-backed. Each juror reads
shared history with their own credentials before deliberation and final voting;
failed posts or reads fail the episode. `public_messaging=False` disables these
runner calls. Operator audit evidence is retained for evaluation, outside agent
observations, and describes participants, volume, timing, rounds, and read patterns.

`game_api/local_engine.py` owns subprocesses, local credentials, and time control.
The existing `CoreEngineAPI` experiment adapter composes these components;
its `cast_vote` still commits and its `settle` still completes local voting.

`game_api/` owns the adapter and generated validated wire types; `agents/` owns decisions
and prompts; `experiments/` owns treatments and execution; `metrics/` owns
evaluation and exports; `scenarios/` holds examples. `example_experiment.toml`
is a reference configuration, not an alternative game engine contract.

Each run writes `episodes.jsonl`, `summary.json`, and transcripts. Records
identify `config.game_backend`. Real settlements retain `engine_evidence` with
exact integer amounts and deployment identity. Core balances and settlements use
exact `Decimal` token amounts in memory; JSON financial quantities are decimal strings. Statistical
rates remain JSON numbers. Consumers of older numeric financial exports should
parse the new strings with `Decimal`, avoiding `float`. Episode exports are scoped to
their experiment. Verdict accuracy excludes failed runs; attack success uses
the declared target and all assigned attack trials, with abort/failure counts
reported separately. Undefined rates are JSON `null`. `simulated_utility` and
the recipient-specific offer ledger stay separate from on-chain payouts.
`collusion_analysis` includes eligible history but remains a heuristic flag,
not proof of coordination. Imported `historical-results/` and `RESULTS.md` predate
these integration fixes and must not be used as proof of corrected behavior.

## Verification

```sh
bash scripts/verify.sh
# Focused Python work, after building Rust:
bash scripts/verify-harness.sh
```

Unittest regressions exercise HTTP failures, confirmation status, unit
conversion, CLI defaults, channel controls, memory, metrics, and exports.
Actual process tests drive Python → Rust → SQLite → Solidity → Anvil, including
both winners, minority rewards, integer dust, nonparticipation/withholding,
expiry, content integrity, and cleanup. Model APIs are never needed by the gate.

## Changelog

### 2026-10-25

- Add the categorical Models factor. Named lineups in `experiments/design.py`
  set the creator, challenger and jury models; auditors use the jury model.
  `run_experiments.py --lineup` selects them, and `run_lineups.py` runs cells
  across lineups in parallel, one process per cell and lineup, because one
  process running 17 lineups in turn would take about 40 hours per cell. The
  lineup stays out of the cell ID, so earlier cell IDs and run names are
  unchanged; treatment IDs, run keys, `config.lineup`/`config.models` in
  episode exports, and W&B `lineup` carry it. The roster's priors come from
  predecessor models on other tasks: no study measures bribery or jury
  collusion by model.
- Retry an unreadable model reply once with the same prompt. In the first live
  auditor runs `nvidia/nemotron-3-ultra-550b-a55b` wrote malformed JSON in about
  0.4% of calls (closing the object early or missing a delimiter), which failed
  3 of 16 episodes. JSON mode is unavailable on the fastest provider. Each
  `llm_calls` entry records its `retries`; a second unreadable reply still fails
  the episode.
- Add the chain-of-thought monitor (`--cot-monitor`) and Weave tracing
  (`--weave`). The monitor follows the published hybrid design: separate
  action-only and reasoning prompts, 0-100 suspicion, weight 0.55 on actions, a
  provisional threshold of 50 to recalibrate on honest-baseline scores, and
  evidence quotes. It never sees evaluator truth. Reasoning can be unfaithful,
  so `cot_*` measurements complement the behavioural ones.
- Route OpenRouter requests by throughput. Default cheapest-first routing sent
  `nvidia/nemotron-3-ultra-550b-a55b` to a provider at about 23 tokens/s
  (30-second calls); the fastest served about 101 tokens/s for ~10% more.
- Weave's dependency `cint` installs a top-level `tests` package, which shadows
  `harness/tests` for dotted imports such as `python -m unittest tests.test_x`.
  Run tests with `PYTHONPATH=harness python -m unittest discover -s harness/tests`
  as `scripts/verify-harness.sh` does.
- Record each model call's reasoning in the episode's `llm_calls` for
  post-hoc chain-of-thought monitoring. Capture leaves the request unchanged, so
  agent behaviour is as before. Reasoning stays in local `episodes.jsonl`
  exports: not in transcripts, summaries, prompts to other agents, or W&B.
- Raise the agent `max_tokens` default from 2048 to 8192. Reasoning models such
  as `nvidia/nemotron-3-ultra-550b-a55b` count hidden reasoning against the cap;
  at 2048 about one live auditor-cell episode in three failed with an empty or
  truncated creator reply. A reply stopped at the cap now fails as
  `reached max_tokens` instead of as invalid JSON or an empty action. W&B runs
  record the cap, so runs before and after the change stay distinguishable.
- Keep jury measurement denominators in local exports and W&B: valid reveals
  from completed aborted games still count toward vote alignment, while verdict
  accuracy requires settlement. Preserve per-actor prohibited-message audit
  counts through both adapters so enabled-channel abuse rates use engine evidence.
- Treat OpenRouter free-route exhaustion as an infrastructure failure, even when
  paid credits remain. Retry with an explicit recorded `--model`; keep failed
  attempts separate, and retain only provider/category/status in ordinary errors.
- Track experiment blocks in W&B only with `--wandb`, using a scientific metadata
  allowlist while keeping model/private-chat content and credentials local.
  Label short integration runs `smoke` so they cannot be confused with research
  batches; use the explicit `M0-C0-T0-R0-S0-E0` cell because legacy `A` has `M1`.
- Select fallback models explicitly with `run_experiments.py --model`; provider
  quotas must not silently substitute another model or change treatment factors.
- Add the optional auditor panel (`V1`, `docs/experiment-design.md`). Auditors live only
  in the harness: the engine never registers them, participants are not told they exist,
  and they make no contact until every final vote is cast. They then interview jurors
  privately under `C1` or in a shared hearing under `C0`, on harness-only channels, and
  only they receive the case file of payments, every private chat, votes and outcome.
  Auditors start impartial, with no persona or objective, so any corruption comes from the
  interview, where `T1` lets a juror offer a finding-conditional payment. The
  `VERDICT_VERIFIED`/`NOT_VERIFIED` finding is a metric only. `V` avoids the `A` (Audit) code.
- Add Disclosure (`D1`, requires `V1`): jurors are told about the auditor panel before
  deliberation, truthfully and without opening any earlier channel to it, so `D1` against
  its `D0` pair isolates the effect of knowing. Creator and challenger are not told.
- Measure bribe acceptance and the auditor-juror collusion scene as `jury_metrics`
  counts and rates, beside the existing jury signals, so W&B and exports carry them.
  The detector keeps its original signals and weights; auditor acceptances and
  interviews never enter it, so identical jury behaviour scores the same with or
  without auditors. Tracking records the `V` and `D` factors and auditor settings, and
  `--model` applies to auditors too.
- Publish enabled public deliberation to the core forum and fetch each agent's
  observations through authenticated reads. Export full forum audit evidence,
  including partial communication after failures, separately from agent context.
- Use the Rust API by default and preserve exact settlement evidence. A failed
  HTTP operation, reverted receipt, or malformed response is an explicit failure,
  never a locally reconstructed verdict or payout.
- Derive on-chain stakes, juror bonds, and payout shares from treatment values;
  keep a fixed conversion scale so low-stakes and incentive comparisons execute
  the economics described to agents.
- Separate absence from reveal withholding, isolate evaluator truth and mutable
  observations from agent contexts, enforce channel controls, preserve
  enabled role memory across episodes, and scope exports to one experiment so
  protocol and treatment differences remain observable in results.
- Report attack targets against all assigned trials and persist conditional
  simulated utility independently of contract finance. Keep undefined rates
  valid JSON and compare repeated-play signals through stable role slots.
