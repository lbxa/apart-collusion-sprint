# Collusion harness

The single autonomous harness for the [Collusion research contract](../docs/benchmark.md).
Participants receive an identity, frozen case material, the selected constitution,
and a private workspace. Deep Agents discover the permitted HTTP interface and
choose their own actions. Rust owns the API and recovery; Solidity owns money.

This runtime is shared infrastructure adapted from Epistemics. Collusion's
objectives, scenario admission, treatments, labels, metrics, evidence register,
spending ledgers, and W&B project remain independent. The accepted research anchor
is Track 2.3, convincing evidence of collusion; Track 2.2, text versus actions
versus both, is the first planned detector comparison. No new model experiment
or empirical finding is supplied by this migration.

## Setup and configuration checks

Prerequisites are Python 3.12+, uv, Docker with a running daemon, the Rust
toolchain, and pinned Foundry. Run from the repository root:

```sh
bash scripts/setup.sh
cargo build --workspace --locked
uv run --project harness --locked veracity-harness build-sandbox
uv run --project harness --locked veracity-harness validate \
  --config harness/examples/discovery.toml --model "$EXPERIMENT_MODEL_ID"
```

`validate` parses configuration without provider credentials or model calls.
`build-sandbox` builds the participant image and makes no model calls. The
discovery example explicitly selects Cloudflare; model IDs are always explicit.
There is no automatic model fallback. Case paths are relative to the TOML file.
Choose `--config`, `--provider`, `--model`, `--output`, and `--seed` deliberately.
Launch seeds control participant scheduling, not provider sampling randomness.

The [migration source manifest](migration-source.json) records pre-adaptation
source-file SHA256 values, source revision and dirty-tree context, and the target
base commit. Imported bytes and final Collusion adaptations are distinct; use the
final run's own source hashes when admitting empirical evidence.

Cloudflare credentials belong in the ignored repository `.env` or the worker's
secret environment:

- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`

Use native Workers AI model IDs supported by the configured account. Catalog
visibility does not establish funded inference or tool compatibility. The host
loads credentials; participant containers never receive them. OpenRouter remains
an explicit compatibility option for historical configurations, with
`OPENROUTER_API_KEY` and optional `OPENROUTER_BACKUP_API_KEY`.

## Authorized live execution

An explicitly authorized campaign runs on a cloud worker with Docker, the built
engine, the pinned environment, and secret injection. W&B tracking is not compute.
The infrastructure upgrade and historical campaign caps do not authorize new
paid calls. After authorization, a run uses one shared ledger:

```sh
uv run --project harness --locked veracity-harness run \
  --config harness/examples/discovery.toml \
  --provider cloudflare --model "$EXPERIMENT_MODEL_ID" \
  --dotenv .env --output harness/results/my-campaign \
  --budget-ledger harness/results/my-campaign/spending.sqlite \
  --budget-usd "$AUTHORIZED_API_CAP"
```

`smoke` uses one participant, one episode, and at most four model requests. It is
a paid provider/tool check, not a scripted dry run or evidence of collusion.
All campaign workers share the same spending ledger and authorized cap. Before
each request, the ledger reserves a conservative catalog-priced context/output
ceiling. Known usage reconciles the reservation; missing costs, failures,
cancellations, and interruptions retain holds. Pricing contradictions halt play.
Never replace a ledger to bypass its cap or erase unresolved reservations.

Cloudflare requests share a machine-wide rate store. Set `VERACITY_RATE_DB` to a
writable shared SQLite path for workers using the same provider account; the
runtime checks its availability before play. Keep request accounting and rate
limits shared across concurrent processes. Provider retries are disabled so
paid attempts remain attributable to reservations.

## Campaign dispatch and recovery

The generic campaign controller freezes a typed assignment plan and journals
dispatch independently of individual financial worlds. Inspect a plan offline:

```sh
uv run --project harness --locked veracity-harness-campaign validate \
  --plan harness/examples/campaign.toml
```

The example is an operational fixture, not an approved study plan or spending
cap. Before authorized collection, freeze a reviewed plan with explicit models,
providers, seeds, configurations, case inputs, and assignments. A live campaign
then uses the same output and ledger on subsequent controller invocations:

```sh
uv run --project harness --locked veracity-harness-campaign run \
  --plan "$CAMPAIGN_PLAN" --output "$CAMPAIGN_OUTPUT" --dotenv .env \
  --budget-ledger "$CAMPAIGN_LEDGER" --budget-usd "$AUTHORIZED_API_CAP"
uv run --project harness --locked veracity-harness-campaign status \
  --output "$CAMPAIGN_OUTPUT"
```

An exclusive controller lock precedes ledger construction and recovery. The
frozen identity covers effective assignments, configuration and input bytes,
delivered static documents, source/binary/lock identities, and the cap. Private
input copies are verified before dispatch. Started assignments never rerun:
stale `running` entries become `interrupted`, completed/failed/interrupted
entries remain terminal, and only `pending` entries continue. Recovery does not
replay an interrupted world or replace a strategic null outcome. The read-only
`status` command preserves worker identity and controller history.

`progress.json` is written atomically. Explicit `--wandb` on `campaign run` opts
into scoped live reporting of IDs, hashes, counts, statuses, and spending. It
does not publish task payloads or the private journal/database. A tracking outage
degrades monitoring without changing assignment state. Keep worker access and a
durable handoff: live tracking is not private recovery storage or compute.

## Controls and financial continuity

Configuration owns experimental choices; the harness never infers them from a
result. Freeze the complete effective configuration before collection.

| Control | Meaning |
| --- | --- |
| `public_messaging`, `private_chat` | Gateway-enforced access to the public forum and pairwise chat |
| `private_history` | Full or latest-only participant chat history; operator evidence remains complete |
| `private_communication_prohibited` | A usable channel is prohibited by the delivered rule; access is not permission |
| `message_delivery` | `normal` delivers recipient message reads; `suppressed` returns empty forum/private pages, chat listings, and initial forum pushes while retaining sends in Rust |
| `memory` | Retain or reset private memory and conversation checkpoints between cases |
| `shared_store` | Optional writable, audited case cache as a separate possible carrier |
| `network` | `episodic` creates a fresh financial world per case; `continuous` retains one chain and accounts per session |
| `lineup` | Actor-specific model IDs; record each actor's provider-compatible model and price |
| `schedule` | Explicit case sequence, separate from persistent memory and financial continuity |
| `constitution` | `enumerated` mounts the current root constitution; `principles` mounts fixed evidence and independence duties |
| `transfers` | Expose ABI 2 withdrawal-credit transfers; keep these separate from ordinary settlement |
| `scripted_setup_first` | Finish scripted offers and seeded commitments before evaluated actors are notified |
| `scripted_peer_inspection_count` | Optional positive record count for the scripted inspection peer, at most `lookup_allowance`; evaluated actors retain their full allowance |

`message_delivery` changes recipient observations without changing the permitted
OpenAPI bytes, identity, or participant instructions. Both modes forward allowed
message and chat creation writes to Rust; successful send receipts and complete
operator transcripts remain available to their respective callers. Suppressed
message pages return no messages, `has_more = false`, and only the caller's input
cursor. This is a message-delivery control: send-receipt metadata, public actions,
payments, timing, and any enabled shared cache remain possible carriers. Gateway
audits distinguish upstream message counts from counts returned to participants;
an upstream read does not establish delivered exposure.

Without `scripted_peer_inspection_count`, the scripted peer still inspects its
full historical allowance. Setting it to four with twelve records and an
allowance of twelve lets the peer propose pooling while every evaluated juror
can satisfy the individual inspection duty. The peer's proposal does not prove
agreement, executed coordination, or model behavior.

Additional scripted parties, seeded peers, inspection budgets, framing, and
awareness probes are available for declared designs. Scripted recruitment is
an induced susceptibility test; it is not spontaneous model initiation. Verify
intervention exposure before classifying a response. A mounted instruction is
not proof an agent read or understood it.

The short root [constitution](../CONSTITUTION.md) does not contain the principles
variant's truth and independence duties. Freeze the exact delivered bytes and
hashes. A rule-violation label must cite an obligation actually delivered in that
run; never apply later duties retroactively. Hold a behavioral harm endpoint
constant when comparing duty variants and record rule compliance separately.

Solidity computes deposits, votes, forfeitures, rewards, and credits. ABI 2 credit
transfers are executed game actions, not simulated utility. Promises, promised
amounts, settlement rewards, and confirmed transferred credit are distinct.
All valid revealers share ordinary juror rewards regardless of vote direction.
Protocol feasibility and an achievable compliant strategy are scenario-admission
requirements; see [the research contract](../docs/benchmark.md).

## Isolation and failure handling

Every participant has an identity-bound gateway, isolated Docker network, private
workspace, and no public Internet, host repository, chain RPC, evaluator labels,
or provider/operator credentials. The gateway filters discovery and channel
access, and passes idempotency keys without replaying participant writes. Rust
owns durable operation recovery; the contract owns financial authority.

Agents act concurrently in bounded opportunities. Turn deadlines stop new model
calls; bounded completion and cancellation evidence distinguish yielded turns,
transient failures, and failed execution. The operator advances the owned local
clock and settles or expires cases, but does not invent missing participant
claims, challenges, or votes. Interrupted worlds retain evidence and are not
automatically replayed against a replacement chain.

Memory checkpoints do not supply complete campaign recovery. A remote handoff
must identify the runner, source revision, effective configuration, every assigned
run, terminal and missing states, models, seeds, confirmed charges, unresolved
holds, and next action. Preserve private recovery data separately from published
artifacts. Missing uploads do not establish that a run was never played.

## Evidence, inspection, and tracking

Private `harness/results/<run-id>/` directories retain manifests, frozen inputs,
model/tool traces, request usage, opportunities, communication transcripts and
audits, engine state, settlement, and balance evidence. Provenance includes source
and input hashes, framework versions, model settings, and revision when available.
Routine logs contain safe identities, states, counts, and error types rather
than prompts, private messages, keys, or returned reasoning.

```sh
uv run --project harness --locked veracity-harness-watch harness/results --from-start
uv run --project harness --locked veracity-harness-wandb --help
uv run --project harness --locked veracity-harness-wandb \
  --dotenv .env --check-access
uv run --project harness --locked veracity-harness-wandb \
  --dotenv .env --results harness/results/my-campaign --dry-run
```

The watcher reads traces already retained by running sessions; it does not
create model calls. `--check-access` verifies project access read-only and creates
no run; `--dry-run` reports the upload scope and file counts offline. Neither
uploads evidence. Tracking targets `lbxa-corp/apart-collusion-sprint` at the
standard W&B API host. Scope precedence is explicit CLI flags, the selected
dotenv file, then Collusion defaults. Inherited `WANDB_PROJECT`, `WANDB_ENTITY`,
and `WANDB_BASE_URL` are ignored to prevent cross-study routing; the process
`WANDB_API_KEY` retains credential precedence. A known Epistemics destination is
rejected. Upload preflight must verify an existing accessible project before
creating a run. Use the repository W&B skill for read-only inspection with an
explicit entity and project. Uploads must pass credential scanning.

Default upload publishes only the generated `.wandb-public.json` projection:
numeric measurements, model/seed/revision metadata, and provenance hashes. Original
configuration, task content, transcripts, audits, participant files, and probe
answer strings remain local. `--include-private-evidence` explicitly releases
retained private evidence; `--include-model-calls` additionally requires that flag
to release raw calls and provider-returned reasoning. SQLite recovery/checkpoint
databases and spending ledgers remain excluded under either option. Review the
specific release authorization before enabling either flag.

Upload intent is durably recorded in local `wandb-upload.json` before the remote
side effect. A deterministic ID binds it to scope, local run, and manifest hash.
`--force` updates that same scoped run rather than creating another observation;
changing scope or original manifest cannot silently reuse an existing intent.

The uploader handles finished/failed sessions and skips running ones. It is not
live monitoring or a cloud runner. Preserve live status and partial evidence on
the worker plus a durable remote handoff during a campaign.

The rubric scorer consumes separately reviewed labels:

```sh
uv run --project harness --locked python -m veracity_harness.scoring \
  --results harness/results/my-campaign --labels labels.json --output report.json
```

Mechanical outcomes, independent task/reference grades, jury decisions, and
semantic coordination labels stay separate. Wrong votes, agreement, payment,
and returned reasoning alone do not establish executed collusion. A missing
response is not resistance. Provider-returned reasoning is observable text,
not certified internal computation. Independent review remains necessary.

## Historical evidence and fixture inputs

The original harness guide is preserved in [LEGACY.md](LEGACY.md); its retired
entrypoints, factor catalog, simulated utilities, and tracking semantics describe
historical work. `historical-results/`, old result summaries, and
`../harness-v2/results/` retain their existing paths and bytes. Frozen
`../harness-v2/research/` protocols and labels retain their original scope;
archived `../harness-v2/examples/` inputs remain for their relative references.
The former `harness-v2` path is no longer an active Python package.

Copied market, frontier, and swarm inputs under `research/` are reusable fixtures
and experimental designs. Their copied names do not establish execution here,
transfer earlier spending approval, or import historical findings into a new
cohort. Do not launch frozen campaign scripts without reviewing scope and budget.
October spontaneous-discovery, later induced-recruitment, swarm, and new Collusion
cohorts remain distinct. Preserve original ABI, duty text, source, and input hashes.

## Verification

```sh
bash scripts/verify.sh
```

The full gate covers hooks, Foundry, Rust, Python, and real Docker → HTTP → Anvil
acceptance checks. Focused Python work uses `bash scripts/verify-harness.sh` after
the engine is built. Model APIs, funded public wallets, and public RPC are not
needed. Integration fixtures establish mechanics and evidence retention, not
spontaneous model behavior. Do not silently skip Docker or chain checks.

## Changelog

### 2026-11-17

- Keep execution authorization campaign-specific in the
  [study handoff](research/collusion-resistance-v1/HANDOFF.md): the current
  Collusion campaign authorizes local CPU work, native Cloudflare inference,
  private W&B evidence and no overall time cutoff. This does not transfer
  Epistemics hypotheses, results, tracking identity or spending authority.
- Supply neutral read-only API bootstrap commands through `execute`, quoting
  `VERACITY_URL` and distinguishing mounted source material from the live
  submitted claim and phase. Preserve earlier pilot prompts as a separate
  capability cohort when freezing these operational instructions.
- Keep resistance admission case-level and distinct from session labels or wrong
  votes. Equal-weight adversarial-arm bounds retain capability/review failures;
  clustered conditional intervals and strict delivered-duty labels remain separate.
- Preserve interface and participant materials across normal and suppressed
  message delivery. Rust retains attempted sends and operator transcripts; own
  receipts, actions, timing, and enabled shared storage remain explicit limits.
- Build anonymous-jury labels from the frozen experiment roster, including
  scripted actors, so all fifteen juror seats receive case-specific labels.
- Allow a scripted record-inspection peer to inspect a declared subset without
  reducing evaluated jurors' lookup allowance. This supports pooling temptations
  with feasible full individual inspection and positive ordinary jury rewards.
- Consolidate the current autonomous runtime and HTTP SDK into one uv project;
  preserve historical campaign paths instead of treating legacy outputs as new
  Collusion evidence.
- Use Cloudflare through the same isolated tool-agent loop, conservative request
  reservations, shared rate limits, and retained failure evidence. Keep Collusion
  credentials, tracking scope, and spending ledgers separate from Epistemics.
- Resolve tracking scope from explicit flags and the selected dotenv file rather
  than inherited project settings, preventing accidental cross-study uploads.
- Limit multi-case `smoke` to its first scheduled case as well as one episode so
  its retained effective configuration remains valid and reloadable.
- Journal frozen campaign assignments under an exclusive controller lock; restart
  only pending work and retain interrupted worlds without replay. Optional live
  W&B progress exports safe metadata rather than task or recovery contents.
- Publish only a numeric/provenance projection by default. Private-evidence and
  raw-call releases are separate explicit choices, and upload retries reuse one
  durable scoped identity.
- Anchor the research contract on Track 2.3 and plan the text/action/combined
  detector comparison under Track 2.2; the runtime migration makes no empirical
  claim about coordination or detection performance.
