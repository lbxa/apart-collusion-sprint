# Collusion resistance v1 inputs

This directory contains prospective study inputs, not results. Read the
[protocol](PROTOCOL.md) and the repository's [measurement contract](../../../docs/benchmark.md)
before creating assignments. The [operator-only source registry](scenario-bank.json)
binds the adapted documents to upstream tasks, reference checks, attribution and
SHA256 values. Only `cases/*.md` is participant source material; the registry,
protocol, reviewer labels and assignment plan stay outside participant sandboxes.

The six confirmation configurations contain the same two cases, in the same
order: `finance_return`, then `education_roster`. The five-source pilot is an
exploratory capability check and must not enter confirmation denominators.

| Input | Purpose |
| --- | --- |
| [pilot-one-case.toml](pilot-one-case.toml) | One false-claim capability check before broader collection |
| [pilot-five-source.toml](pilot-five-source.toml) | Exploratory five-source capability pilot |
| [honest-false.toml](honest-false.toml) | No-offer false-claim adjudication baseline |
| [paid-false-basic.toml](paid-false-basic.toml) | Induced paid false-publication opportunity under the short constitution |
| [paid-false-suppressed.toml](paid-false-suppressed.toml) | Same paid opportunity with message-read delivery suppressed |
| [paid-false-principles.toml](paid-false-principles.toml) | Same paid opportunity with stronger delivered duties |
| [honest-true.toml](honest-true.toml) | No-offer true-claim adjudication baseline |
| [paid-rejection-basic.toml](paid-rejection-basic.toml) | Induced paid wrongful-rejection opportunity under the short constitution |

## Operator ingestion and plans

[`ingest.py`](ingest.py) reads the immutable register and campaign journals, then
writes a new private derived register, mechanical readout, claim-bound review
packets, private original-locator map, and hashed receipt. Select the frozen
cohort through `PYTHONPATH=<runtime>/harness/src`; the receipt records the runtime,
interpreter, helper source, and output hashes. Authoritative registers, raw runs,
and previous outputs remain unchanged.

Use `collect --register ... --registry ... --campaign ... --output <new-dir>`;
repeat `--campaign` for journals from the same runtime. Running jobs remain
unpinned/deferred. Missing terminal evidence and inconsistent journal/run states
are explicit gaps. Missing capability files yield presence/hash metadata and
null counts, never assumed zero activity. Packets retain delivery facts; core
communication reads alone do not prove exposure. Literal identity masking is
provisional, not independently verified blinding.

`prepare --runtime-root ... --output <new-candidate-dir> --seeds 701 702 703 704 705`
creates the full pending frame without dispatch. The cost-only amendment also
needs `--priority-primary`, `--previous-plan`, `--protocol-amendment`, and
`--cost-basis`. The candidate retains the exact prior cells/configurations,
copies the prior plan and amendment/cost evidence, and writes five disjoint
family shards. Receipt union/order checks precede root-owned launch under one
shared ledger and cap.

Callback starts/ends include scripted-party callbacks and are not paid request
counts. Evaluated opportunities, provider/ledger receipts, budget events, and
ordinary/extra game payments remain separate. The twenty scripted callbacks in
the initial one-case pilots must not be described as blocked paid requests or
call-limit violations.

[`amend_budget.py`](amend_budget.py) applies an explicit higher cap to a stopped
journal after the shared ledger has recorded the same authorization. Select the
original frozen runtime with `PYTHONPATH`, supply the original plan, old/new
caps, exact ledger authorization and a new backup directory. It rejects changed
source or assignments, running jobs, halted ledgers and missing authorization.
Verified backups precede a transaction that retains both frozen records and
identity aliases while preserving all jobs and controller history. The tracking
marker is backed up before removal; the restarted controller creates the new
identity. Never rerun an already committed old-cap amendment. If a projection
write fails after commit, inspect the retained audit and backups before manual
recovery; do not reset the journal or replace the ledger.

## Private audit archives

`archive.py` snapshots explicitly selected runs, frozen runtime source, benchmark
documents and safe campaign metadata. It includes raw model calls, delivered
prompts, tool traces and outcome evidence under the study's explicit private
release authorization. Originals remain unchanged. Each artifact has original
and export SHA256 values; its receipt records the immutable version, W&B digest,
and a verified SDK download checked against both manifests. Its receipt records
whether the SDK cache was enabled. Credential-bearing files,
wallet keys, recovery databases and spending ledgers stay local.

Use `--watch --upload --phase <name>` for each explicitly approved phase, with a
frozen `--runtime-root`, `--campaign-root`, new `--stage` directory, selected
`--dotenv`, provider `--scan-env`, `--campaign-id` and absolute UTC `--deadline`.
The watcher uploads changed content every 90 seconds by default. Missing phases
remain pending, and later terminal writes remain observable. A bounded 60-second
archive-only grace captures finalization after the inference deadline. A new
runtime or phase set requires a separate watcher identity and stage directory.
Use explicit `--no-deadline` instead of `--deadline` when authorized to monitor
until the declared controllers stop. It records the lifetime choice in its
binding, keeps pending/incomplete evidence distinct from controller termination,
and verifies then re-observes final content before exiting. Start the intended
controllers before this watcher. Use a new stage for a changed lifetime policy;
retain old watcher stages with their original frozen helper and identity.
`--log-finished-runs` also calls the retained finished-session tracker with both
private-evidence release flags. Run this operator process through the same
OS-managed detachment used for campaign controllers.
Pass absolute filesystem paths for operator roots, `--run`, `--campaign-file`
and `--benchmark-file`; only the explicit `--phase` names are path components.

`--use-sdk-cache-for-verification` opts periodic watch downloads into W&B's
official artifact cache. Each version still has a fresh exact-version API
lookup and digest comparison, SDK manifest verification, and SHA256 checks for
every payload. Receipts identify `sdk_cache_enabled`; they do not establish that
every byte was newly fetched over the network. Uncached files still need a
download. One-off uploads keep `skip_cache=True` by default. No custom cache or
cache cleanup is introduced.

Manifest schema `collusion-private-audit-v2` reconciles assignment rows and
counts with canonical run directories, terminal run identity, episode count,
and retained episode evidence. Required execution evidence includes opportunity,
gateway, actor trace/call, configured setup and transfer records. Mandatory
frozen source files and directories also have explicit gap records. Missing or
inconsistent evidence stays explicit as assignment, phase or source gaps.
Verification checks the strict manifest schema,
unique file/run identities, canonical content hash, file hashes, and completion
against retained assignment and episode records. A watcher exits unsuccessfully
if its final observed content lacks a matching verified v2 receipt.

For long campaigns, `--prune-verified-payloads` explicitly opts into removing an
owned local snapshot's payload copies only after a matching persisted v2 receipt
and another snapshot verification. Its manifest and receipt stay local, all
immutable remote versions remain, and raw runs, frozen sources, databases and
unverified staging directories remain untouched. Pruned metadata cannot be
republished as a full snapshot; a new observation reads the retained originals.

Historical v1 receipts remain evidence that their listed exported bytes were
downloaded and matched their file hashes. Their completion status did not have
the v2 assignment reconciliation or canonical metadata validation, and their
watcher exit code did not establish final upload success. Preserve those
receipts and use a new v2 receipt for a completeness claim.

## Changelog

### 2026-11-17

- The current campaign has no overall time cutoff, a US$300 **total** model API
  cap and a US$280 threshold for starting assignments, preserving headroom for
  active work and unresolved billing. Removing the time limit leaves the
  spending authority and original ledger unchanged;
  see the [time-policy decision](../../../docs/decisions/remove-the-campaign-deadline-with-explicit-authorization.md).
- Overall campaign time policy is explicit: choose `--deadline` or
  `--no-deadline`, never both. Unlimited operation retains the same API cap,
  journal and frozen participant runtime; it does not replay interrupted worlds.
  The private watcher must keep incomplete/pending evidence distinct from
  stopped controllers and verify its final observed bytes before success.
- Include the frozen tools and Docker credential-helper directories explicitly
  in launchd `PATH`; its default path can pass daemon connectivity yet fail
  image startup before participant/model activity. Verify the actual background
  environment with the existing Docker isolation test before dispatch. Keep
  startup failures terminal and link any separately collected recovery attempts;
  never silently replace them in confirmation denominators.
- A failure at `sandbox_image` can follow engine episode registration, so empty
  completed-episode lists or absent model-call files do not establish that a
  world never started. Determine recovery eligibility from retained lifecycle
  evidence and record new attempt identities separately.
- An authorized API cap increase retains the original spending ledger and every
  unknown request hold; the frozen campaign fingerprint includes the cap, so
  resuming needs an audited cap-only journal amendment with backups and an
  old-to-new identity link. Preserve every job row and earlier remote run,
  resume pending assignments only, and amend time authority separately.
- Use launchd property lists with `KeepAlive=false`, `RunAtLoad=true` and no
  `OnDemand` key for one-shot controllers. `OnDemand=false` implies restart
  behavior, and historical failed assignments can produce a nonzero controller
  exit even after a budget stop; see the [cap/recovery decision](../../../docs/decisions/preserve-campaign-evidence-when-increasing-the-api-cap.md).
- Enforce the recorded absolute UTC boundary with `deadline_guard.py` when
  relative waits can be extended by host sleep. Capture exact owned identities;
  SIGTERM and any five-second SIGKILL escalation never target changed processes.
  This operator guard starts no work and leaves journals and holds intact.
- Keep the local laptop lid open during execution. The observed 18:00:55–18:24:34
  UTC clamshell sleep suspended workers despite active `caffeinate -i` assertions,
  interrupted provider connections and left unknown billing holds. Preserve
  those attempts and holds; do not replay started worlds or count missing
  responses as resistance. `host-interruption-audit.json` records the incident
  and the diagnostic suspension/resumption of the same processes.
- Allow the official W&B cache for periodic verification while retaining all
  payload integrity checks and recording the cache policy in each receipt.
  Fresh whole-archive downloads remain the one-off default.
- Ingest each cohort under its frozen runtime; retain terminal-state and missing
  capability gaps explicitly, with unblinded locators separate from provisional
  review packets. Scheduling changes preserve every pending assignment and bind
  exact amendment, cost-evidence, and family-shard hashes.
- Require v2 manifest validation and assignment-to-run reconciliation before
  describing an audit as complete. Preserve earlier receipts with their original
  verification limits; final watcher success requires the latest observed
  content to have its own verified receipt.
- Keep versioned private audit snapshots separate from recovery databases and
  original evidence. Bind each periodic watcher to one frozen runtime and an
  explicit phase list; unchanged content creates no new version, and missing
  phases never become completed observations.
- Freeze the FinQA calculation and MathDial arithmetic adaptation for the
  budgeted confirmation comparison before its outcomes; keep broader source
  coverage in an exploratory pilot. Every model receives every frozen case
  at every seed, so source identity is not confounded with the seed label.
- Keep the normal paid false-publication and wrongful-rejection arms in the
  primary score. Message suppression, stronger duties, capability pilots and
  optional role/procedure extensions have separate estimands.
- Preserve the communication interface in the suppression control and withhold
  message-read delivery only. Action and other permitted carriers remain, so
  this control does not establish absence of every coordination channel.
