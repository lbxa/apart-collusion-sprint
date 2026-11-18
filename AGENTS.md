# Repository Guidelines

## Project Structure & Module Organization

This is the independent Collusion Sprint project. New environments, tracking,
and campaign metadata use `apart-collusion-sprint`; retain Veracity's package and
API names. Shared execution code does not merge Collusion's empirical objectives
with Epistemics. Read `.agents/skills/README.md` for local routing.

This repository implements the `SPEC.md` game engine and `/v1` API plus the Python experiment harness in `harness/`. `core/src/` contains `api`, `game`, `chain`, `chat`, `forum`, `store`, and configuration modules. `contracts/` owns Solidity rules, Foundry tests, and the deployment artifact. The harness owns agents, treatments, observations, and metrics; it calls HTTP. Keep financial authority in the contract.

`harness/` is the sole active Python project, containing `veracity_harness` and
the retained `game_api` HTTP SDK under `src/`. Do not restore a second harness or
the retired structured-action entrypoints. `harness-v2/research/` and
`harness-v2/results/` are historical records, not active package roots. Preserve
their bytes, paths, source hashes, ABI versions, and original duty text.

`docs/api.md` is the harness integration guide; `docs/architecture.md` records boundaries. `configs/` and `examples/` contain deployment and request templates. Shared skills live in `.agents/skills/`; `.claude/skills` points there. Agent definitions and hooks live in `.codex/` and `.claude/`.

`docs/private-chat.md` defines the experimental chat API. Prohibited chat is delivered and flagged; membership is enforced. Participant history settings never remove the operator's retained audit transcript. Keep chat bodies out of public game state and logs.

`docs/public-forum.md` defines the core-owned public forum. Assigned episode participants share history; operator transcript/audit access is distinct. The harness publishes and reads public deliberation through HTTP. Keep message bodies out of ordinary logs and metadata audits.

## Build, Test, and Development Commands

- `bash scripts/setup.sh`: install pinned local Foundry, build contracts, and fetch locked dependencies.
- `cargo run -p veracity-game-service -- --local`: start the API with isolated Anvil.
- `bash scripts/verify.sh`: run hooks, Solidity/Rust tests, artifact checks, formatting, Clippy, and builds.
- `cargo build --workspace --locked`: build workspace packages.
- `cargo test --workspace --locked`: run unit, integration, and documentation tests.
- `cargo test -p veracity-game-service`: test the service during iteration.
- `bash scripts/verify-harness.sh`: run Python regressions and real engine acceptance tests after building Rust.
- `cargo fmt --all`: format Rust sources.
- `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`: reject lint warnings.

Rust tooling is pinned in `rust-toolchain.toml`; Foundry in `.foundry-version`.
Commit `Cargo.lock`, `harness/uv.lock`, and intentional artifact updates. Setup
requires uv and creates `harness/.venv`. Run the harness with
`uv run --project harness --locked veracity-harness ...` from the repository root.
`validate` makes no model calls; both `run` and `smoke` are paid commands requiring
an explicit model and authorized shared spending ledger. Use Cloudflare for new
designs unless the experiment explicitly selects another provider.

## Coding Style & Naming Conventions

Use Rust 2024 and rustfmt's default four-space indentation. Use `snake_case` for modules, functions, and variables; `PascalCase` for types and traits; and `SCREAMING_SNAKE_CASE` for constants. Prefer explicit ownership, typed errors, and narrow module boundaries. Share dependency versions through `[workspace.dependencies]` when needed. Workspace members inherit the unsafe-code prohibition.

## Testing Guidelines

Follow the shared `tdd` skill: witness the intended failure, implement, and expand
outward. Rust integration tests live in `core/tests/`, contract tests in
`contracts/test/`, and Python pytest regressions in `harness/tests/`. Prove
deadlines, conservation, commitments, role boundaries, and recovery with actual
Anvil. Default tests require no public networks, funded public wallets, or model
APIs. Never skip Docker or chain tests silently. No coverage percentage is configured.

## Collusion research authority

Anchor the paper on Track 2.3, convincing evidence of collusion. Track 2.2,
text-only versus action-only versus combined detection, is the first planned
comparative experiment. `docs/benchmark.md` defines scenario admission, evidence
rungs, independent review, denominators, and uncertainty. Implementation and
fixture checks do not constitute model-behavior evidence.

Keep proposal, agreement, implementing action, success, and capability failure
separate. A wrong verdict, shared error, message, or payment alone is not
executed collusion. Cite the actual submitted claim and the exact obligation
delivered to participants; the short root constitution omits duties present in
the `principles` variant. Freeze rule text, not only its configuration name.
Do not apply new duties or truth labels retroactively to historical campaigns.

Reuse benchmark tasks as source material, then admit a feasible collusion
opportunity, an achievable compliant strategy, and observable harm. Evaluator
labels and coalition plans stay outside participant inputs. Reference grades,
jury outcomes, contract settlement, and semantic coordination labels are distinct.
Agent annotations remain provisional until independent review. Juror seats and
repeated cases are not automatically independent statistical replicates.

## Cloud execution and tracking isolation

New paid campaigns run on an explicitly selected cloud worker with the required
Docker/engine runtime. W&B supplies tracking and artifacts, not compute. Prior
campaign caps and provider keys do not authorize new spending or publication.

Keep this repository's ignored `.env` and spending ledger separate from Epistemics.
Cloudflare uses host-only `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`;
participants must never receive provider/operator credentials or evaluator data.
Reuse one immutable authorized ledger across campaign workers, preserve unknown
request holds, and never replace a ledger to bypass exhaustion.

Use the repository's `wandb-primary` skill. The verified scope is
`lbxa-corp/apart-collusion-sprint` at `https://api.wandb.ai`, unless the user
explicitly selects another destination. Historical Forge URLs are evidence
addresses, not authority to send a supplied key to another host. Never print keys,
pass them as command-line arguments, or include them in source or artifacts.
For connection checks, use read-only project access; do not create dummy runs.

Recover cloud state before dispatch: runner identity, source/configuration,
assignments, run IDs/URLs, models, seeds, charges/holds, and next action. Preserve
live status and partial evidence remotely. Finished-run upload skips running
sessions and does not provide complete recovery. SQLite recovery/checkpoint
databases and spending ledgers remain separate from ordinary artifacts; raw
model calls require explicit opt-in and release authorization. Missing uploads
do not prove a run was unplayed.

The default uploader publishes only numeric/provenance projections. Private
evidence requires `--include-private-evidence`; raw calls additionally require
`--include-model-calls`. Upload intent and deterministic scoped IDs prevent an
uncertain upload retry from silently creating another experimental observation.
The campaign controller journals immutable assignments, continues only pending
work, and marks stale running work interrupted without replay. Its optional
`--wandb` observer exports safe progress, not private input or journal contents.

## Decision records

Capture durable package facts in the affected README changelog. Record choices
with real trade-offs under `docs/decisions/`, preserving append-only history and
marking unverified rationale explicitly. Do not manufacture experimental results
to justify an infrastructure change.

## Commit & Pull Request Guidelines

Use focused, imperative subjects such as `Add Cargo verification hooks`. Pull requests should describe behavior, link spec sections or issues, and report verification results and blockers.

## Agent-Specific Instructions

Use Context7 for current dependency and tool documentation: resolve the library ID, then query the full question. Author source and documentation directly with editing tools. Never commit wallet keys, credentials, or private observations. Both Stop hooks share `scripts/agent-hooks/stop-checks.sh`; disclose failures even when a repeated failure permits handoff.

## Research Reports

A LaTeX research report is a main project deliverable. Before planning, drafting,
or reviewing a report, use the [reporting guide and table of contents](docs/reporting/README.md).
Read in this order:

1. [Paper brief](docs/reporting/paper-brief.md): reader, research question, actual evidence, and unresolved claims.
2. [Venue](docs/reporting/venue.md): selected official template and submission rules. Venue requirements take precedence over house formatting.
3. [Writing](docs/reporting/writing.md): argument, mathematical exposition, and reader comprehension.
4. [Visuals](docs/reporting/visuals.md) and [LaTeX](docs/reporting/latex.md): figures, tables, diagrams, notation, and build conventions.
5. [Review](docs/reporting/review.md): evidence, compilation, and rendered-page acceptance checks.

Update the brief as evidence changes. Do not turn historical, mock, scripted, or
heuristic outputs into claims about model behavior on the integrated protocol.
Report completion requires the brief's claim-to-evidence mapping, a reproducible
PDF build, final-size visual inspection, and a recorded review with open gaps.
Source notes and reusable examples are indexed in the reporting guide; consult
them for technical lookup rather than expanding this entry point.
The older baseline manuscript lives in `report/main.tex`, with prose in
`report/sections/` and shared formatting in `report/preamble.tex`; build it with
`make -C report`. The October agentic manuscript is `report/agentic/main.tex`,
built with `make -C report agentic`. Consult the paper brief for each evidence
set. Historical model-backed records and fictional teaching examples retain
their original scopes; neither is a new result of the harness upgrade.
